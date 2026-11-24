"""내보내기: 원본 해상도·보이는 방향으로 디코딩 → 인물별(구간별) 효과 → FFmpeg(VideoToolbox HEVC), 오디오는 원본 복사."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import cv2
import numpy as np

from .effects import apply, clip_box, cover_box
from .project import Project
from .video import color_tags, iter_frames, tool, video_time_base

SOURCE_COLORS = {"auto": (0, 1, 0), "interp": (0, 0.8, 1), "manual": (1, 0, 1)}  # BGR 비율

CODECS = ("hevc", "h264")
QUALITY = {"high": 1.0, "normal": 0.55, "small": 0.3}  # 원본 비트레이트 대비
RESOLUTIONS = (2160, 1440, 1080, 720)  # 짧은 변 기준


@dataclass
class ExportOptions:
    codec: str = "hevc"  # hevc: 작고 선명 / h264: 어디서나 재생
    quality: str = "high"  # high(원본 수준) / normal / small
    height: int | None = None  # 짧은 변 픽셀 (None = 원본)

    def scale(self, w: int, h: int) -> float:
        return 1.0 if not self.height else min(1.0, self.height / min(w, h))

    def size(self, w: int, h: int) -> tuple[int, int]:
        k = self.scale(w, h)
        return round(w * k) // 2 * 2, round(h * k) // 2 * 2

    def bitrate(self, v) -> int:
        """출력 비트레이트(bps). 원본 비트레이트 × 화질 × 해상도 비율. H.264는 같은 화질에 더 많이 필요."""
        base = v.bitrate or int(v.width * v.height * v.fps * 0.1)
        if v.codec in ("hevc", "h265", "av1", "vp9") and self.codec == "h264":
            base *= 1.5
        k = self.scale(v.width, v.height)
        return max(300_000, int(base * 1.1 * QUALITY[self.quality] * k * k))

    def high_bit(self, v) -> bool:
        return v.high_bit and self.codec == "hevc"  # H.264(하드웨어)는 8bit만

    def estimate_mb(self, v, seconds: float) -> float:
        audio = 192_000 if v.has_audio else 0
        return (self.bitrate(v) + audio) * seconds / 8 / 1e6


def compose(img: np.ndarray, frame: int, p: Project, per: dict, scale: float = 1.0, debug: bool = False):
    """한 프레임에 효과를 입힌다. 내보내기와 미리보기가 같이 쓴다. scale은 미리보기 축소 비율."""
    h, w = img.shape[:2]
    hi = 65535 if img.dtype == np.uint16 else 255
    for tid, b, src in per.get(frame, []):
        pid = p.tracks[tid].person
        effect = p.effect_for(pid, frame)
        area = cover_box([x * scale for x in b[:4]], effect)
        apply(img, area, effect, p.time_of(frame))
        if debug:
            box = clip_box(area, w, h)
            color = tuple(c * hi for c in SOURCE_COLORS[src])
            cv2.rectangle(img, box[:2], box[2:], color, max(1, int(3 * scale)))
            cv2.putText(img, f"#{pid}", (box[0], max(20, box[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        max(0.5, scale), color, max(1, int(2 * scale)))


def encoder_args(p: Project, opts: ExportOptions | None = None) -> list[str]:
    opts = opts or ExportOptions()
    v = p.video
    if opts.codec == "h264":
        args = ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-b:v", str(opts.bitrate(v)), "-pix_fmt", "yuv420p"]
    else:
        args = ["-c:v", "hevc_videotoolbox", "-b:v", str(opts.bitrate(v)), "-tag:v", "hvc1"]
        args += ["-profile:v", "main10", "-pix_fmt", "p010le"] if opts.high_bit(v) else ["-pix_fmt", "yuv420p"]
    # 원본 색 정보(HDR 등) 유지: primaries/trc는 출력 옵션만으로는 변환 과정에서 빠져서 프레임에 직접 붙인다
    params = [f"{k}={v.color[k]}" for k in ("color_primaries", "color_trc") if k in v.color]
    if params:
        args += ["-vf", "setparams=" + ":".join(params)]
    for k, val in v.color.items():
        args += [f"-{k}", val]
    return args


def render(p: Project, out: str | Path, debug: bool = False, progress=None, cancel=None,
           opts: ExportOptions | None = None) -> float:
    """cancel: 호출 시 True를 돌려주면 중단 (화면에서 취소 버튼용). 중단되면 출력 파일을 지운다."""
    opts = opts or ExportOptions()
    v = p.video
    v.color = color_tags(v.path)  # 저장된 분석이 오래됐어도 원본 색 정보를 그대로 따르도록 매번 다시 읽음
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    high = opts.high_bit(v)
    pix = "bgr48le" if high else "bgr24"
    k = opts.scale(v.width, v.height)
    out_w, out_h = opts.size(v.width, v.height)
    tb = video_time_base(v)
    # 프레임을 원본 시각(pts)과 함께 NUT 형식으로 넘겨 가변 프레임레이트 영상도 소리와 어긋나지 않게 한다
    cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "nut", "-i", "-",
           "-i", v.path, "-map", "0:v", "-map", "1:a?", "-c:a", "copy",
           *encoder_args(p, opts), "-fps_mode", "passthrough", "-enc_time_base:v", "demux", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    per = p.boxes_by_frame()
    t0 = time.perf_counter()
    cancelled = broken = False
    try:
        with av.open(proc.stdin, "w", format="nut") as mux:
            vs = mux.add_stream("rawvideo", rate=Fraction(v.rate))
            vs.width, vs.height, vs.pix_fmt = out_w, out_h, pix
            vs.time_base = vs.codec_context.time_base = tb
            max_side = round(max(v.width, v.height) * k) if k < 1 else None
            for i, pts, img in iter_frames(v, max_side=max_side, high_bit=high, raw_pts=True):
                if cancel and cancel():
                    cancelled = True
                    break
                if img.shape[1] != out_w or img.shape[0] != out_h:
                    img = cv2.resize(img, (out_w, out_h), interpolation=cv2.INTER_AREA)
                compose(img, i, p, per, scale=out_w / v.width, debug=debug)
                frame = av.VideoFrame.from_ndarray(img, format=pix)
                frame.pts, frame.time_base = pts, tb
                for packet in vs.encode(frame):
                    mux.mux(packet)
                if progress and i % 15 == 0:
                    progress(i, p.n_frames)
            for packet in vs.encode(None):
                mux.mux(packet)
    except BrokenPipeError:
        broken = True  # ffmpeg가 먼저 끝남 (오류)
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait()
    if cancelled:
        out.unlink(missing_ok=True)
        raise InterruptedError("내보내기 취소됨")
    if proc.returncode or broken:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg 인코딩 실패 (코드 {proc.returncode})")
    return time.perf_counter() - t0
