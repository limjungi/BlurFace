"""프로젝트 파일: 분석 결과와 사용자 수정·설정을 저장한다.

영상 옆 `<이름>.blurface/project.json`에 저장.
- auto: 자동 분석 결과 (바꾸지 않음)
- tracks: 사람이 고칠 수 있는 트랙. 자동 결과를 가리키고(auto, span) 그 위에 수동 키프레임(keys)과 지운 구간(removed)을 얹는다
- persons: 인물 이름·효과·구간 효과
실제로 가릴 상자는 track_boxes()가 이 셋을 합쳐 계산한다.
"""

from __future__ import annotations

import bisect
import copy
import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .effects import SHAPES
from .video import VideoInfo

BACKUP_KEEP = 10  # 백업을 최근 몇 개까지 남길지
VERSION = 3  # 2: 프레임 시각(pts), 구간 효과 / 3: 수동 수정(키프레임·지운 구간·트랙 나누기)

EFFECT_TYPES = ("mosaic", "blur", "solid", "sticker", "image", "none")
DEFAULT_EFFECT = {"type": "blur", "value": 30.0, "shape": "ellipse", "feather": 20.0}


OPTION_KEYS = ("shape", "feather", "scale")


def parse_effect(spec: str) -> dict:
    """'mosaic', 'mosaic:12', 'blur:30', 'solid:#000000', 'sticker:smile', 'image:경로.png', 'none'

    뒤에 쉼표로 옵션: 'blur:30,shape=ellipse,feather=20,scale=120'
    (shape: rect|rounded|ellipse, feather: 가장자리 부드럽게 0~50, scale: 가리는 범위 50~300%)
    """
    head = spec.split(":", 1)[0].split(",", 1)[0]  # 'mosaic,scale=120'처럼 값 없이 옵션만 줘도 됨
    rest = spec[len(head):].removeprefix(":")
    kind = head.strip().lower()
    if kind not in EFFECT_TYPES:
        raise ValueError(f"알 수 없는 효과: {kind} (가능: {', '.join(EFFECT_TYPES)})")
    parts = rest.split(",") if rest else [""]
    opts: dict = {}
    while parts and parts[-1].split("=", 1)[0].strip() in OPTION_KEYS and "=" in parts[-1]:
        k, v = parts.pop().split("=", 1)
        opts[k.strip()] = v.strip()
    value = ",".join(parts)
    e = _parse_value(kind, value)
    if "shape" in opts:
        if opts["shape"] not in SHAPES:
            raise ValueError(f"알 수 없는 모양: {opts['shape']} (가능: {', '.join(SHAPES)})")
        e["shape"] = opts["shape"]
    if "feather" in opts:
        e["feather"] = min(50.0, max(0.0, float(opts["feather"])))
    if "scale" in opts:
        e["scale"] = min(300.0, max(50.0, float(opts["scale"])))
    return e


def _parse_value(kind: str, value: str) -> dict:
    if kind in ("mosaic", "blur"):
        return {"type": kind, "value": float(value) if value else (8 if kind == "mosaic" else 30)}
    if kind == "solid":
        return {"type": kind, "value": value or "#000000"}
    if kind == "sticker":
        return {"type": kind, "value": value or "smile"}
    if kind == "image":
        if not value or not Path(value).expanduser().exists():
            raise ValueError(f"이미지 파일을 찾을 수 없음: {value}")
        return {"type": kind, "value": str(Path(value).expanduser().resolve())}
    return {"type": "none", "value": None}


def effect_label(e: dict) -> str:
    s = e["type"] if e.get("value") in (None, "") else f"{e['type']}:{e['value']}"
    return s + "".join(f",{k}={e[k]}" for k in OPTION_KEYS if k in e)


@dataclass
class AutoTrack:
    """자동 분석 결과 (분석 후 바뀌지 않음)."""
    frames: list[int]
    boxes: list[list[float]]  # [x1, y1, x2, y2, score]
    sources: list[str]  # auto | interp


@dataclass
class Track:
    """편집 가능한 트랙."""
    person: int
    auto: int | None = None  # 자동 결과 번호. None이면 사람이 직접 그린 트랙
    span: list[int] = field(default_factory=lambda: [0, 1 << 30])  # 이 트랙이 쓰는 자동 결과 범위 [시작, 끝)
    keys: dict[int, list[float]] = field(default_factory=dict)  # 수동 키프레임 {프레임: [x1, y1, x2, y2]}
    removed: list[list[int]] = field(default_factory=list)  # 지운 구간 [[시작, 끝), ...]


@dataclass
class Person:
    name: str
    tracks: list[int]
    thumb: list[float]  # [frame, x1, y1, x2, y2]
    effect: dict | None = None  # None이면 기본 효과
    # 구간 효과: [{"start": 시작 프레임, "end": 끝 프레임(포함 안 함), "effect": {...}}]. 겹치면 나중 것이 우선
    segments: list[dict] = field(default_factory=list)


@dataclass
class Project:
    video: VideoInfo
    n_frames: int
    cuts: list[int]
    tracks: dict[int, Track] = field(default_factory=dict)
    persons: dict[int, Person] = field(default_factory=dict)
    default_effect: dict = field(default_factory=lambda: dict(DEFAULT_EFFECT))
    timings: dict = field(default_factory=dict)
    pts: list[float] = field(default_factory=list)  # 프레임별 시각(초)
    auto: dict[int, AutoTrack] = field(default_factory=dict)

    def __post_init__(self):
        self._cache: dict[int, dict] = {}
        self._per: dict | None = None

    @staticmethod
    def dir_for(video: str | Path) -> Path:
        v = Path(video)
        return v.with_name(v.stem + ".blurface")

    @property
    def dir(self) -> Path:
        return self.dir_for(self.video.path)

    def effect_for(self, pid: int, frame: int | None = None) -> dict:
        """frame을 주면 그 시점의 구간 효과까지 반영한 효과."""
        p = self.persons.get(pid)
        if p is None:
            return self.default_effect
        if frame is not None:
            for seg in reversed(p.segments):
                if seg["start"] <= frame < seg["end"]:
                    return seg["effect"]
        return p.effect or self.default_effect

    def add_segment(self, pid: int, start: int, end: int, effect: dict):
        start, end = max(0, min(start, end)), min(self.n_frames, max(start, end))
        if end > start:
            self.persons[pid].segments.append({"start": start, "end": end, "effect": effect})

    def frame_at(self, seconds: float) -> int:
        """시각(초) → 프레임 번호."""
        if self.pts:
            import bisect
            return min(len(self.pts) - 1, bisect.bisect_left(self.pts, seconds - 1e-6))
        return int(round(seconds * self.video.fps))

    def time_of(self, frame: int) -> float:
        if self.pts and 0 <= frame < len(self.pts):
            return self.pts[frame]
        return frame / self.video.fps

    def needs_review(self, pid: int) -> bool:
        """점수가 낮거나 아주 잠깐 나온 인물 (손·뒤통수 같은 오검출이거나 흐린 얼굴일 수 있음)."""
        boxes = [b for t in self.persons[pid].tracks for b in self.track_boxes(t).values()]
        if not boxes:
            return False  # 모두 지운 인물
        if len(boxes) < self.video.fps * 0.5:
            return True
        scores = sorted(b[0][4] for b in boxes if b[1] == "auto")
        if not scores:
            return False  # 모두 사람이 그린 상자
        return scores[int(len(scores) * 0.75)] < 0.7

    def person_frames(self, pid: int) -> list[int]:
        return sorted({f for t in self.persons[pid].tracks for f in self.track_boxes(t)})

    # ---------- 실제로 가릴 상자 계산 ----------
    def track_boxes(self, tid: int) -> dict[int, tuple[list[float], str]]:
        """{프레임: ([x1, y1, x2, y2, score], source)}. source: auto | interp | manual"""
        if tid in self._cache:
            return self._cache[tid]
        t = self.tracks[tid]
        lo, hi = t.span
        out: dict[int, tuple[list[float], str]] = {}
        base: dict[int, list[float]] = {}
        if t.auto is not None and t.auto in self.auto:
            a = self.auto[t.auto]
            i0, i1 = bisect.bisect_left(a.frames, lo), bisect.bisect_left(a.frames, hi)
            for f, b, s in zip(a.frames[i0:i1], a.boxes[i0:i1], a.sources[i0:i1]):
                out[f] = (list(b), s)
                base[f] = b
        keys = sorted(t.keys.items())
        if keys:
            fade = max(1, round(self.video.fps * 0.5))
            delta = {f: (np.subtract(k, base[f][:4]) if f in base else None) for f, k in keys}
            for (fa, ka), (fb, kb) in zip(keys, keys[1:]):
                da, db = delta[fa], delta[fb]
                for f in range(fa, fb + 1):
                    w = (f - fa) / (fb - fa)
                    if f in base and da is not None and db is not None:
                        # 자동 상자 움직임은 살리고, 사람이 고친 차이만 이어서 적용
                        box = np.add(base[f][:4], da * (1 - w) + db * w)
                    else:
                        box = np.multiply(ka, 1 - w) + np.multiply(kb, w)
                    out[f] = ([*map(float, box), 1.0], "manual")
            for f, k in keys:
                out[f] = ([*map(float, k), 1.0], "manual")
            # 처음·마지막 키프레임 바깥은 고친 차이를 0.5초에 걸쳐 서서히 없앤다
            for edge, sign in ((keys[0][0], -1), (keys[-1][0], 1)):
                d = delta[edge]
                if d is None:
                    continue
                for step in range(1, fade):
                    f = edge + sign * step
                    if f in base:
                        w = 1 - step / fade
                        out[f] = ([*map(float, np.add(base[f][:4], d * w)), base[f][4]], "manual")
        for a, b in t.removed:
            for f in [f for f in out if a <= f < b]:
                del out[f]
        self._cache[tid] = out
        return out

    def boxes_by_frame(self) -> dict[int, list[tuple[int, list[float], str]]]:
        if self._per is None:
            per: dict[int, list] = {}
            for tid in self.tracks:
                for f, (b, s) in self.track_boxes(tid).items():
                    per.setdefault(f, []).append((tid, b, s))
            self._per = per
        return self._per

    def _touch(self, *tids: int):
        for t in tids:
            self._cache.pop(t, None)
        self._per = None

    def _reindex(self, drop_empty: bool = True):
        """인물별 트랙 목록을 다시 만들고, 트랙이 하나도 없는 인물은 지운다."""
        for p in self.persons.values():
            p.tracks = []
        for tid, t in sorted(self.tracks.items()):
            if t.person in self.persons:
                self.persons[t.person].tracks.append(tid)
        if drop_empty:
            for pid in [pid for pid, p in self.persons.items() if not p.tracks]:
                del self.persons[pid]

    # ---------- 수정 ----------
    def set_key(self, tid: int, frame: int, box: list[float]):
        self.tracks[tid].keys[frame] = [float(x) for x in box[:4]]
        self._touch(tid)

    def clear_key(self, tid: int, frame: int | None = None):
        """frame이 None이면 그 트랙의 키프레임을 모두 지운다 (자동 결과로 되돌리기)."""
        t = self.tracks[tid]
        if frame is None:
            t.keys.clear()
        else:
            t.keys.pop(frame, None)
        self._touch(tid)

    def new_person(self, name: str | None = None, thumb: list[float] | None = None) -> int:
        pid = max(self.persons, default=-1) + 1
        self.persons[pid] = Person(name or f"인물 {pid}", [], thumb or [])
        return pid

    def add_manual_track(self, frame: int, box: list[float], pid: int | None = None) -> int:
        if pid is None or pid not in self.persons:
            pid = self.new_person(thumb=[frame, *box[:4]])
        tid = max(self.tracks, default=-1) + 1
        self.tracks[tid] = Track(pid, None, [0, 0], {frame: [float(x) for x in box[:4]]})
        self._reindex()
        self._touch(tid)
        return tid

    def remove_range(self, tid: int, start: int, end: int):
        """[start, end) 구간의 상자를 지운다 (얼굴이 아닌 것을 잡았을 때)."""
        if end <= start:
            return
        rs = sorted([*self.tracks[tid].removed, [start, end]])
        merged: list[list[int]] = []
        for a, b in rs:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.tracks[tid].removed = merged
        self._touch(tid)

    def remove_track(self, tid: int):
        self.remove_range(tid, 0, self.n_frames)

    def remove_person(self, pid: int):
        """얼굴이 아닌 것(손·뒤통수 등)으로 판단해 인물째 지운다."""
        for tid in list(self.persons[pid].tracks):
            self.remove_track(tid)
            self.tracks[tid].person = -1
        self._reindex()

    def split_track(self, tid: int, frame: int) -> int:
        """frame부터 뒤쪽을 새 트랙으로 떼어낸다 (두 사람이 한 트랙에 섞였을 때)."""
        t = self.tracks[tid]
        new = max(self.tracks) + 1
        lo, hi = t.span
        self.tracks[new] = Track(t.person, t.auto, [max(lo, frame), hi],
                                 {f: k for f, k in t.keys.items() if f >= frame}, copy.deepcopy(t.removed))
        t.span = [lo, min(hi, frame)]
        t.keys = {f: k for f, k in t.keys.items() if f < frame}
        self._reindex()
        self._touch(tid, new)
        return new

    def assign_track(self, tid: int, pid: int | None) -> int:
        """트랙을 다른 인물로 옮긴다. pid가 None이면 새 인물을 만든다."""
        if pid is None or pid not in self.persons:
            frames = self.track_boxes(tid)
            f = next(iter(sorted(frames)), 0)
            pid = self.new_person(thumb=[f, *frames[f][0][:4]] if frames else [])
        self.tracks[tid].person = pid
        self._reindex()
        self._touch(tid)
        return pid

    def merge_persons(self, target: int, others: list[int]):
        """others의 트랙을 모두 target으로 옮긴다. 이름·효과·구간 효과는 target 것을 쓴다."""
        for pid in others:
            if pid == target or pid not in self.persons:
                continue
            for tid in self.persons[pid].tracks:
                self.tracks[tid].person = target
        self._reindex()
        self._touch()

    # ---------- 실행 취소용 상태 ----------
    def edit_state(self) -> dict:
        return {"persons": copy.deepcopy(self.persons), "tracks": copy.deepcopy(self.tracks),
                "default_effect": copy.deepcopy(self.default_effect)}

    def restore_state(self, state: dict):
        self.persons = copy.deepcopy(state["persons"])
        self.tracks = copy.deepcopy(state["tracks"])
        self.default_effect = copy.deepcopy(state["default_effect"])
        self._cache.clear()
        self._per = None

    # ---------- 검토가 필요한 곳 ----------
    def review_points(self) -> list[tuple[int, int, str]]:
        """자동 추적이 틀렸을 수 있는 위치 (프레임, 인물, 이유)."""
        pts: list[tuple[int, int, str]] = []
        min_gap = max(3, round(self.video.fps * 0.2))
        for tid, t in self.tracks.items():
            boxes = self.track_boxes(tid)
            if not boxes:
                continue
            frames = sorted(boxes)
            if t.person in self.persons and self.needs_review(t.person):
                pts.append((frames[0], t.person, f"{self.persons[t.person].name}: 얼굴이 맞는지 확인"))
            run_start, run_kind, run_len = None, None, 0
            for f in frames + [None]:
                b = boxes.get(f) if f is not None else None
                kind = None
                if b is not None and b[1] == "interp":
                    kind = "검출이 끊겨 이어 붙인 구간"
                elif b is not None and b[1] == "auto" and b[0][4] < 0.5:
                    kind = "검출 점수 낮음"
                if kind == run_kind and kind is not None and f == run_start + run_len:
                    run_len += 1
                    continue
                if run_kind and run_len >= min_gap and t.person in self.persons:
                    pts.append((run_start, t.person, f"{self.persons[t.person].name}: {run_kind}"))
                run_start, run_kind, run_len = f, kind, 1
        return sorted(set(pts))

    def save(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / "project.json"
        data = {
            "version": VERSION,
            "video": asdict(self.video),
            "n_frames": self.n_frames,
            "cuts": self.cuts,
            "default_effect": self.default_effect,
            "persons": {str(k): asdict(v) for k, v in self.persons.items()},
            "auto": {str(k): {"frames": a.frames,
                              "boxes": [[round(x, 1) for x in b[:4]] + [round(b[4], 3)] for b in a.boxes],
                              "sources": a.sources} for k, a in self.auto.items()},
            "tracks": {str(k): {"person": t.person, "auto": t.auto, "span": t.span,
                                "keys": {str(f): [round(x, 1) for x in b] for f, b in t.keys.items()},
                                "removed": t.removed} for k, t in self.tracks.items()},
            "timings": self.timings,
            "pts": [round(x, 6) for x in self.pts],
        }
        path.write_text(json.dumps(data, ensure_ascii=False))
        return path

    # ---------- 백업 (다시 분석하기 전 상태 보관) ----------
    @classmethod
    def backup(cls, video: str | Path) -> Path | None:
        """지금 저장된 상태(project.json, 얼굴 사진)를 backups/<시각>/에 복사. 저장된 게 없으면 None."""
        d = cls.dir_for(video)
        if not (d / "project.json").exists():
            return None
        root = d / "backups"
        dst = root / time.strftime("%Y-%m-%d_%H%M%S")
        n = 1
        while dst.exists():
            n += 1
            dst = root / f"{time.strftime('%Y-%m-%d_%H%M%S')}_{n}"
        dst.mkdir(parents=True)
        shutil.copy2(d / "project.json", dst / "project.json")
        if (d / "faces").exists():
            shutil.copytree(d / "faces", dst / "faces")
        for old in cls.backups(video)[BACKUP_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
        return dst

    @classmethod
    def backups(cls, video: str | Path) -> list[Path]:
        """백업 목록 (최신이 먼저)."""
        root = cls.dir_for(video) / "backups"
        if not root.exists():
            return []
        return sorted((b for b in root.iterdir() if (b / "project.json").exists()),
                      key=lambda b: (b / "project.json").stat().st_mtime, reverse=True)

    @staticmethod
    def backup_summary(backup: Path) -> str:
        """목록에 보여줄 한 줄 설명."""
        try:
            d = json.loads((backup / "project.json").read_text())
        except (OSError, ValueError):
            return backup.name
        when = time.strftime("%m월 %d일 %H:%M", time.localtime((backup / "project.json").stat().st_mtime))
        edits = sum(1 for t in d.get("tracks", {}).values()
                    if t.get("keys") or t.get("removed") or ("auto" in t and t["auto"] is None))
        effects = sum(1 for p in d.get("persons", {}).values() if p.get("effect") or p.get("segments"))
        return f"{when} · 인물 {len(d.get('persons', {}))}명 · 효과 지정 {effects}명 · 고친 상자 {edits}개"

    @classmethod
    def restore(cls, video: str | Path, backup: Path) -> Project | None:
        """백업으로 되돌린다. 되돌리기 직전 상태도 백업해 두어 다시 돌아올 수 있게 한다."""
        d = cls.dir_for(video)
        data = (backup / "project.json").read_bytes()
        faces = backup / "faces"
        tmp_faces = None
        if faces.exists():  # 현재 상태 백업 중 오래된 백업이 지워질 수 있어 먼저 따로 복사
            tmp_faces = d / ".restore_faces"
            shutil.rmtree(tmp_faces, ignore_errors=True)
            shutil.copytree(faces, tmp_faces)
        cls.backup(video)
        (d / "project.json").write_bytes(data)
        if tmp_faces:
            shutil.rmtree(d / "faces", ignore_errors=True)
            tmp_faces.rename(d / "faces")
        return cls.load(video)

    @classmethod
    def load(cls, video: str | Path) -> Project | None:
        path = cls.dir_for(video) / "project.json"
        if not path.exists():
            return None
        d = json.loads(path.read_text())
        if d.get("version") == 2:  # 이전 형식: 트랙 = 자동 결과. 수정 없는 새 형식으로 옮긴다
            d["auto"] = {k: {"frames": t["frames"], "boxes": t["boxes"], "sources": t["sources"]}
                         for k, t in d["tracks"].items()}
            d["tracks"] = {k: {"person": t["person"], "auto": int(k)} for k, t in d["tracks"].items()}
        elif d.get("version") != VERSION:
            return None
        p = cls(VideoInfo(**d["video"]), d["n_frames"], d["cuts"], default_effect=d["default_effect"],
                timings=d.get("timings", {}), pts=d.get("pts", []))
        p.persons = {int(k): Person(**v) for k, v in d["persons"].items()}
        p.video.path = str(video)  # 영상을 옮겼거나 상대 경로로 저장됐어도 지금 연 위치를 기준으로
        p.auto = {int(k): AutoTrack(**v) for k, v in d.get("auto", {}).items()}
        p.tracks = {}
        for k, v in d["tracks"].items():
            v = dict(v)
            v["keys"] = {int(f): b for f, b in v.get("keys", {}).items()}
            p.tracks[int(k)] = Track(**v)
        p._reindex(drop_empty=False)
        return p
