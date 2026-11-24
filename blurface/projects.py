"""프로젝트 보관함: 모든 프로젝트를 한곳(기본 ~/Movies/BlurFace)에 모은다.

- 프로젝트 = `<보관함>/<영상 이름>.blurface/` 폴더 (project.json, meta.json, 얼굴·이미지·백업)
- 원본 영상은 복사하지 않고 위치만 기억한다 (meta.json의 video). 옮겨졌으면 relink()로 다시 연결
- 예전처럼 영상 옆에 있던 `<영상 이름>.blurface/`는 처음 열 때 보관함으로 옮긴다
- 위치 설정: 환경 변수 BLURFACE_PROJECTS > 설정 파일(config.json의 projects_dir) > ~/Movies/BlurFace
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

DEFAULT_ROOT = "~/Movies/BlurFace"
SUFFIX = ".blurface"

_found: dict[str, Path] = {}  # 영상 경로 → 프로젝트 폴더 (찾은 것 기억)


def app_home() -> Path:
    return Path(os.environ.get("BLURFACE_HOME") or "~/Library/Application Support/BlurFace").expanduser()


def _config() -> dict:
    try:
        return json.loads((app_home() / "config.json").read_text())
    except (OSError, ValueError):
        return {}


def root() -> Path:
    env = os.environ.get("BLURFACE_PROJECTS")
    return Path(env or _config().get("projects_dir") or DEFAULT_ROOT).expanduser()


def set_root(path: str | Path, move: bool = False) -> list[str]:
    """보관함 위치를 바꾼다. move면 기존 프로젝트를 새 위치로 옮기고, 옮기지 못한 이름을 돌려준다."""
    new = Path(path).expanduser()
    old = root()
    failed = []
    if move and old.exists() and old.resolve() != new.resolve():
        new.mkdir(parents=True, exist_ok=True)
        for d in _dirs(old):
            target = _unique(new, d.name[: -len(SUFFIX)])
            try:
                shutil.move(str(d), str(target))
            except OSError:
                failed.append(d.name)
    cfg = _config()
    cfg["projects_dir"] = str(new)
    app_home().mkdir(parents=True, exist_ok=True)
    (app_home() / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    _found.clear()
    return failed


def _key(video: str | Path) -> str:
    return str(Path(video).expanduser().resolve())


def _dirs(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [d for d in base.iterdir() if d.is_dir() and d.name.endswith(SUFFIX) and (d / "project.json").exists()]


def _unique(base: Path, stem: str) -> Path:
    d = base / f"{stem}{SUFFIX}"
    i = 2
    while d.exists():
        d = base / f"{stem} {i}{SUFFIX}"
        i += 1
    return d


def read_meta(d: Path) -> dict:
    """meta.json (없으면 project.json에서 만들어 둠)."""
    try:
        return json.loads((d / "meta.json").read_text())
    except (OSError, ValueError):
        pass
    try:
        data = json.loads((d / "project.json").read_text())
    except (OSError, ValueError):
        return {}
    v = data.get("video", {})
    meta = {"video": v.get("path", ""), "name": Path(v.get("path", d.stem)).stem,
            "duration": v.get("n_frames", 0) / max(v.get("fps", 1) or 1, 1e-6),
            "persons": len(data.get("persons", {})), "updated": (d / "project.json").stat().st_mtime}
    write_meta(d, meta)
    return meta


def write_meta(d: Path, meta: dict):
    try:
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    except OSError:
        pass


def dir_for(video: str | Path) -> Path:
    """영상의 프로젝트 폴더. 없으면 새 이름을 정한다 (만들지는 않음). 영상 옆 예전 폴더는 보관함으로 옮긴다."""
    k = _key(video)
    d = _found.get(k)
    if d is not None and d.exists():
        return d
    base = root()
    candidates = _dirs(base) + [Path(x) for x in _config().get("extra", []) if is_project(x)]
    d = next((d for d in candidates if read_meta(d).get("video") and _key(read_meta(d)["video"]) == k), None)
    if d is None:
        v = Path(video)
        legacy = v.with_name(v.stem + SUFFIX)
        d = _unique(base, v.stem)
        if (legacy / "project.json").exists():
            base.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(d))
            meta = read_meta(d)
            meta["video"] = k
            write_meta(d, meta)
    _found[k] = d
    return d


def is_project(path: str | Path) -> bool:
    d = Path(path)
    return d.name.endswith(SUFFIX) and (d / "project.json").exists()


def use_dir(d: str | Path) -> str:
    """.blurface 프로젝트를 직접 골라 열 때: 그 폴더를 쓰도록 기억하고 원본 영상 경로를 돌려준다.

    보관함 밖에 있는 프로젝트(다른 곳에 복사해 둔 것 등)도 목록에 보이게 설정에 적어 둔다.
    """
    d = Path(d).expanduser().resolve()
    video = read_meta(d).get("video", "")
    if video:
        _found[_key(video)] = d
    if d.parent != root().resolve():
        cfg = _config()
        extra = [x for x in cfg.get("extra", []) if x != str(d)] + [str(d)]
        cfg["extra"] = extra[-50:]
        app_home().mkdir(parents=True, exist_ok=True)
        (app_home() / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    return video


def list_projects() -> list[dict]:
    """보관함(과 직접 열었던 보관함 밖) 프로젝트 목록 (최근 수정 순). 각 항목에 dir, video_exists 추가."""
    out = []
    dirs = _dirs(root())
    seen = {d.resolve() for d in dirs}
    dirs += [Path(x) for x in _config().get("extra", []) if is_project(x) and Path(x).resolve() not in seen]
    for d in dirs:
        meta = read_meta(d)
        out.append({**meta, "dir": d, "video_exists": bool(meta.get("video")) and Path(meta["video"]).exists()})
    return sorted(out, key=lambda m: m.get("updated", 0), reverse=True)


def relink(d: Path, video: str | Path):
    """원본 영상을 옮겼을 때 새 위치로 다시 연결."""
    k = _key(video)
    meta = read_meta(d)
    meta["video"] = k
    write_meta(d, meta)
    path = d / "project.json"
    data = json.loads(path.read_text())
    data.setdefault("video", {})["path"] = k
    path.write_text(json.dumps(data, ensure_ascii=False))
    _found[k] = d


def trash(d: Path) -> Path:
    """프로젝트 폴더를 휴지통으로 (원본 영상은 그대로)."""
    bin_ = Path("~/.Trash").expanduser()
    target = bin_ / d.name
    if target.exists():
        target = bin_ / f"{d.stem} {time.strftime('%H%M%S')}{SUFFIX}"
    shutil.move(str(d), str(target))
    for k in [k for k, v in _found.items() if v == d]:
        del _found[k]
    cfg = _config()
    if str(d) in cfg.get("extra", []):
        cfg["extra"].remove(str(d))
        (app_home() / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    return target


def make_cover(d: Path, video: str | Path, frame: int | None = None) -> Path | None:
    """목록에 보여 줄 표지(영상 한 장면, 가로 320px)를 cover.jpg로 저장."""
    import cv2

    from .persons import grab_frames
    from .video import probe
    try:
        info = probe(video)
        if frame is None:
            frame = min(info.n_frames // 10, round(info.fps * 3))
        img = grab_frames(info, {max(0, frame)}).get(max(0, frame))
    except Exception:  # noqa: BLE001 (표지는 없어도 됨)
        return None
    if img is None:
        return None
    h, w = img.shape[:2]
    img = cv2.resize(img, (320, max(1, round(320 * h / w))), interpolation=cv2.INTER_AREA)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "cover.jpg"
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return path
