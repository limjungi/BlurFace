"""프로젝트 파일: 분석 결과(트랙·인물)와 사용자 설정(인물별 효과)을 저장한다.

영상 옆 `<이름>.blurface/project.json`에 저장. 자동 분석 결과(tracks)와 사용자 설정(persons의 effect/name)을
분리해 두어, 다시 분석해도 사용자 설정을 이어받을 수 있게 한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .video import VideoInfo

VERSION = 1

EFFECT_TYPES = ("mosaic", "blur", "solid", "sticker", "image", "none")
DEFAULT_EFFECT = {"type": "mosaic", "value": 8}


def parse_effect(spec: str) -> dict:
    """'mosaic', 'mosaic:12', 'blur:30', 'solid:#000000', 'sticker:smile', 'image:경로.png', 'none'"""
    kind, _, value = spec.partition(":")
    kind = kind.strip().lower()
    if kind not in EFFECT_TYPES:
        raise ValueError(f"알 수 없는 효과: {kind} (가능: {', '.join(EFFECT_TYPES)})")
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
    return e["type"] if e.get("value") in (None, "") else f"{e['type']}:{e['value']}"


@dataclass
class Track:
    person: int
    frames: list[int]
    boxes: list[list[float]]  # [x1, y1, x2, y2, score]
    sources: list[str]  # auto | interp | manual


@dataclass
class Person:
    name: str
    tracks: list[int]
    thumb: list[float]  # [frame, x1, y1, x2, y2]
    effect: dict | None = None  # None이면 기본 효과


@dataclass
class Project:
    video: VideoInfo
    n_frames: int
    cuts: list[int]
    tracks: dict[int, Track] = field(default_factory=dict)
    persons: dict[int, Person] = field(default_factory=dict)
    default_effect: dict = field(default_factory=lambda: dict(DEFAULT_EFFECT))
    timings: dict = field(default_factory=dict)

    @staticmethod
    def dir_for(video: str | Path) -> Path:
        v = Path(video)
        return v.with_name(v.stem + ".blurface")

    @property
    def dir(self) -> Path:
        return self.dir_for(self.video.path)

    def effect_for(self, pid: int) -> dict:
        p = self.persons.get(pid)
        return p.effect if p and p.effect else self.default_effect

    def needs_review(self, pid: int) -> bool:
        """점수가 낮거나 아주 잠깐 나온 인물 (손·뒤통수 같은 오검출이거나 흐린 얼굴일 수 있음)."""
        n_frames = sum(len(self.tracks[t].frames) for t in self.persons[pid].tracks)
        if n_frames < self.video.fps * 0.5:
            return True
        scores = sorted(b[4] for t in self.persons[pid].tracks
                        for b, s in zip(self.tracks[t].boxes, self.tracks[t].sources) if s == "auto")
        return not scores or scores[int(len(scores) * 0.75)] < 0.7

    def boxes_by_frame(self) -> dict[int, list[tuple[int, list[float], str]]]:
        out: dict[int, list] = {}
        for tid, t in self.tracks.items():
            for f, b, s in zip(t.frames, t.boxes, t.sources):
                out.setdefault(f, []).append((tid, b, s))
        return out

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
            "tracks": {str(k): {"person": t.person, "frames": t.frames,
                                "boxes": [[round(x, 1) for x in b[:4]] + [round(b[4], 3)] for b in t.boxes],
                                "sources": t.sources} for k, t in self.tracks.items()},
            "timings": self.timings,
        }
        path.write_text(json.dumps(data, ensure_ascii=False))
        return path

    @classmethod
    def load(cls, video: str | Path) -> Project | None:
        path = cls.dir_for(video) / "project.json"
        if not path.exists():
            return None
        d = json.loads(path.read_text())
        if d.get("version") != VERSION:
            return None
        p = cls(VideoInfo(**d["video"]), d["n_frames"], d["cuts"], default_effect=d["default_effect"],
                timings=d.get("timings", {}))
        p.persons = {int(k): Person(**v) for k, v in d["persons"].items()}
        p.tracks = {int(k): Track(**v) for k, v in d["tracks"].items()}
        return p
