"""내보내기: 원본 해상도·보이는 방향으로 디코딩 → 인물별 효과 → FFmpeg(VideoToolbox HEVC) 인코딩, 오디오는 원본 복사."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import cv2

from .effects import apply, expand_box
from .project import Project
from .video import color_tags, iter_frames


def encoder_args(p: Project) -> list[str]:
    v = p.video
    bitrate = v.bitrate or int(v.width * v.height * v.fps * 0.1)
    args = ["-c:v", "hevc_videotoolbox", "-b:v", str(int(bitrate * 1.1)), "-tag:v", "hvc1"]
    if v.high_bit:
        args += ["-profile:v", "main10", "-pix_fmt", "p010le"]
    else:
        args += ["-pix_fmt", "yuv420p"]
    # 원본 색 정보(HDR 등) 유지: primaries/trc는 출력 옵션만으로는 변환 과정에서 빠져서 프레임에 직접 붙인다
    params = [f"{k}={v.color[k]}" for k in ("color_primaries", "color_trc") if k in v.color]
    if params:
        args += ["-vf", "setparams=" + ":".join(params)]
    for k, val in v.color.items():
        args += [f"-{k}", val]
    return args


def render(p: Project, out: str | Path, debug: bool = False, progress=None) -> float:
    v = p.video
    v.color = color_tags(v.path)  # 저장된 분석이 오래됐어도 원본 색 정보를 그대로 따르도록 매번 다시 읽음
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix = "bgr48le" if v.high_bit else "bgr24"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{v.width}x{v.height}", "-r", v.rate, "-i", "-",
           "-i", v.path, "-map", "0:v", "-map", "1:a?", "-c:a", "copy",
           *encoder_args(p), "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    per = p.boxes_by_frame()
    effects = {pid: p.effect_for(pid) for pid in p.persons}
    t0 = time.perf_counter()
    try:
        for i, _pts, img in iter_frames(v, high_bit=v.high_bit):
            for tid, b, src in per.get(i, []):
                pid = p.tracks[tid].person
                box = expand_box(b, v.width, v.height)
                apply(img, box, effects.get(pid, p.default_effect))
                if debug:
                    hi = 65535 if img.dtype.itemsize == 2 else 255
                    color = {"auto": (0, hi, 0), "interp": (0, hi * 0.8, hi), "manual": (hi, 0, hi)}[src]
                    cv2.rectangle(img, box[:2], box[2:], color, 3)
                    cv2.putText(img, f"P{pid} T{tid}", (box[0], max(20, box[1] - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
            proc.stdin.write(img.tobytes())
            if progress and i % 30 == 0:
                progress(i, p.n_frames)
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode:
        raise RuntimeError(f"ffmpeg 인코딩 실패 (코드 {proc.returncode})")
    return time.perf_counter() - t0
