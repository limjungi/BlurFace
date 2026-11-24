"""내 이미지 보관함: 한 번 올린 스티커 이미지를 앱 폴더에 저장해 어느 영상에서든 바로 고를 수 있게."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def folder() -> Path:
    base = os.environ.get("BLURFACE_HOME") or "~/Library/Application Support/BlurFace"
    return Path(base).expanduser() / "stickers"


def images() -> list[Path]:
    d = folder()
    if not d.exists():
        return []
    return sorted((f for f in d.iterdir() if f.suffix.lower() in EXTS), key=lambda f: f.stat().st_mtime, reverse=True)


def add(path: str | Path) -> Path:
    """보관함에 복사 (같은 내용이면 기존 파일을 그대로 씀)."""
    src = Path(path)
    data = src.read_bytes()
    digest = hashlib.sha1(data).hexdigest()[:8]
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    for f in d.iterdir():
        if f.stem.endswith(digest):
            f.touch()  # 최근에 쓴 것이 앞으로
            return f
    dst = d / f"{src.stem}_{digest}{src.suffix.lower()}"
    shutil.copy2(src, dst)
    dst.touch()
    return dst


def remove(path: str | Path):
    p = Path(path)
    if p.parent == folder():
        p.unlink(missing_ok=True)
