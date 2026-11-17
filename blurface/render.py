"""효과 적용 후 내보내기. 원본 해상도로 디코딩 → 얼굴 영역 모자이크 → FFmpeg(VideoToolbox) 인코딩, 오디오는 원본 복사."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import av
import cv2
import numpy as np

from .analyze import Analysis


def expand(box, w, h, pad_x=0.15, pad_top=0.3, pad_bottom=0.1):
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - bw * pad_x)), max(0, int(y1 - bh * pad_top)),
            min(w, int(x2 + bw * pad_x)), min(h, int(y2 + bh * pad_bottom)))


def mosaic(img: np.ndarray, box, blocks: int = 10):
    x1, y1, x2, y2 = box
    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return
    rw, rh = roi.shape[1], roi.shape[0]
    bs = max(4, rw // blocks)
    small = cv2.resize(roi, (max(1, rw // bs), max(1, rh // bs)), interpolation=cv2.INTER_AREA)
    img[y1:y2, x1:x2] = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)


def frame_boxes(a: Analysis) -> dict[int, list]:
    per = {}
    for tid, boxes in a.tracks.items():
        for f, b in boxes.items():
            per.setdefault(f, []).append((tid, b))
    return per


def render(src: Path, a: Analysis, out: Path, debug: bool = False) -> float:
    with av.open(str(src)) as c:
        vs = c.streams.video[0]
        rate = vs.average_rate
        bitrate = vs.bit_rate or c.bit_rate or 12_000_000
        cc = vs.codec_context
        color = []
        for opt, val in (("-color_primaries", cc.color_primaries), ("-color_trc", cc.color_trc),
                         ("-colorspace", cc.colorspace)):
            name = getattr(val, "name", None)
            if name and name.lower() not in ("unspecified", "reserved"):
                color += [opt, name.lower()]
        has_audio = bool(c.streams.audio)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{a.width}x{a.height}", "-r", str(rate), "-i", "-",
           "-i", str(src), "-map", "0:v"] + (["-map", "1:a", "-c:a", "copy"] if has_audio else []) + [
           "-c:v", "hevc_videotoolbox", "-b:v", str(int(bitrate * 1.2)), "-tag:v", "hvc1",
           "-pix_fmt", "yuv420p", *color, "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    per = frame_boxes(a)
    t0 = time.perf_counter()
    with av.open(str(src)) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        for i, frame in enumerate(c.decode(s)):
            img = frame.to_ndarray(format="bgr24")
            for tid, b in per.get(i, []):
                box = expand(b[:4], a.width, a.height)
                mosaic(img, box)
                if debug:
                    color = (0, 255, 0) if b[5] == "auto" else (0, 200, 255)
                    cv2.rectangle(img, box[:2], box[2:], color, 3)
                    cv2.putText(img, f"#{tid}", (box[0], box[1] - 8), cv2.FONT_HERSHEY_SIMPLEX,
                                1.2, color, 3)
            proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()
    if proc.returncode:
        raise RuntimeError(f"ffmpeg 실패 ({proc.returncode})")
    return time.perf_counter() - t0
