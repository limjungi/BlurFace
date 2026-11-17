"""내보내기: 원본 해상도·보이는 방향으로 디코딩 → 인물별(구간별) 효과 → FFmpeg(VideoToolbox HEVC), 오디오는 원본 복사."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from .effects import apply, expand_box
from .project import Project
from .video import color_tags, iter_frames

SOURCE_COLORS = {"auto": (0, 1, 0), "interp": (0, 0.8, 1), "manual": (1, 0, 1)}  # BGR 비율


def compose(img: np.ndarray, frame: int, p: Project, per: dict, scale: float = 1.0, debug: bool = False):
    """한 프레임에 효과를 입힌다. 내보내기와 미리보기가 같이 쓴다. scale은 미리보기 축소 비율."""
    h, w = img.shape[:2]
    hi = 65535 if img.dtype == np.uint16 else 255
    for tid, b, src in per.get(frame, []):
        pid = p.tracks[tid].person
        box = expand_box([x * scale for x in b[:4]], w, h)
        apply(img, box, p.effect_for(pid, frame))
        if debug:
            color = tuple(c * hi for c in SOURCE_COLORS[src])
            cv2.rectangle(img, box[:2], box[2:], color, max(1, int(3 * scale)))
            cv2.putText(img, f"#{pid}", (box[0], max(20, box[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        max(0.5, scale), color, max(1, int(2 * scale)))


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


def render(p: Project, out: str | Path, debug: bool = False, progress=None, cancel=None) -> float:
    """cancel: 호출 시 True를 돌려주면 중단 (화면에서 취소 버튼용). 중단되면 출력 파일을 지운다."""
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
    t0 = time.perf_counter()
    cancelled = False
    try:
        for i, _pts, img in iter_frames(v, high_bit=v.high_bit):
            if cancel and cancel():
                cancelled = True
                break
            compose(img, i, p, per, debug=debug)
            proc.stdin.write(img.tobytes())
            if progress and i % 15 == 0:
                progress(i, p.n_frames)
    finally:
        proc.stdin.close()
        proc.wait()
    if cancelled:
        out.unlink(missing_ok=True)
        raise InterruptedError("내보내기 취소됨")
    if proc.returncode:
        raise RuntimeError(f"ffmpeg 인코딩 실패 (코드 {proc.returncode})")
    return time.perf_counter() - t0
