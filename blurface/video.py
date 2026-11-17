"""영상 읽기. 회전 정보(아이폰 세로 영상)를 반영해 항상 '보이는 방향'의 프레임을 돌려준다."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import av
import cv2
import numpy as np

ROTATE = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


@dataclass
class VideoInfo:
    path: str
    width: int  # 보이는 방향 기준
    height: int
    fps: float
    rate: str  # "30000/1001" 같은 정확한 값
    n_frames: int  # 추정치 (정확한 값은 분석 후)
    rotation: int  # 시계 방향으로 돌려야 하는 각도 (0/90/180/270)
    high_bit: bool  # 10bit 이상
    codec: str
    bitrate: int
    color: dict  # color_primaries / color_trc / colorspace (ffmpeg 이름)
    has_audio: bool


def color_tags(path: str | Path) -> dict:
    """색 정보(HDR 등)를 ffmpeg 옵션 이름 그대로 읽는다. PyAV는 숫자로만 줘서 ffprobe 사용."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=color_primaries,color_transfer,color_space", "-of", "json", str(path)],
        capture_output=True, text=True, check=False)
    try:
        s = json.loads(out.stdout)["streams"][0]
    except (ValueError, KeyError, IndexError):
        return {}
    tags = {"color_primaries": s.get("color_primaries"), "color_trc": s.get("color_transfer"),
            "colorspace": s.get("color_space")}
    return {k: v for k, v in tags.items() if v and v not in ("unknown", "unspecified", "reserved")}


def probe(path: str | Path) -> VideoInfo:
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        first = next(c.decode(s))
        rotation = int(-(first.rotation or 0)) % 360
        cc = s.codec_context
        w, h = cc.width, cc.height
        if rotation in (90, 270):
            w, h = h, w
        high_bit = any(x in first.format.name for x in ("10", "12", "16"))
        color = color_tags(path)
        fps = float(s.average_rate or s.guessed_rate or 30)
        n = s.frames or round(float(c.duration or 0) / 1e6 * fps)
        return VideoInfo(str(path), w, h, fps, str(s.average_rate or s.guessed_rate), n, rotation, high_bit,
                         cc.name, int(s.bit_rate or c.bit_rate or 0), color, bool(c.streams.audio))


def iter_frames(info: VideoInfo, max_side: int | None = None, high_bit: bool = False):
    """(프레임 번호, pts 초, BGR 이미지)를 순서대로 돌려준다. high_bit이면 uint16(bgr48)."""
    fmt = "bgr48le" if high_bit else "bgr24"
    with av.open(info.path) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        tb = float(s.time_base)
        for i, frame in enumerate(c.decode(s)):
            kw = {}
            if max_side:
                k = min(1.0, max_side / max(info.width, info.height))
                if k < 1:
                    sw, sh = round(frame.width * k), round(frame.height * k)
                    kw = {"width": sw - sw % 2, "height": sh - sh % 2}
            img = frame.to_ndarray(format=fmt, **kw)
            if info.rotation:
                img = cv2.rotate(img, ROTATE[info.rotation])
            yield i, (frame.pts or 0) * tb, np.ascontiguousarray(img)
