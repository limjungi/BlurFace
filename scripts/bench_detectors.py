"""검출기 비교: 영상에서 일정 간격으로 프레임을 뽑아 각 검출기의 속도와 검출 수를 재고, 비교 이미지를 저장한다.

사용: uv run python scripts/bench_detectors.py test_videos/*.mp4 --every 0.5
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import av
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blurface.detect.apple_vision import AppleVision  # noqa: E402
from blurface.detect.scrfd import SCRFD  # noqa: E402
from blurface.detect.yunet import YuNet  # noqa: E402

MODELS = Path(__file__).resolve().parents[1] / "models"
COLORS = [(0, 255, 0), (0, 200, 255), (255, 0, 255), (255, 200, 0), (0, 0, 255)]


def sample_frames(path: Path, every_sec: float, max_side: int = 1920):
    with av.open(str(path)) as c:
        stream = c.streams.video[0]
        stream.thread_type = "AUTO"
        next_t = 0.0
        for frame in c.decode(stream):
            t = float(frame.pts * stream.time_base)
            if t + 1e-6 < next_t:
                continue
            next_t = t + every_sec
            img = frame.to_ndarray(format="bgr24")
            h, w = img.shape[:2]
            s = min(1.0, max_side / max(h, w))
            if s < 1:
                img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
            yield t, img


def draw(img, dets, color, label):
    out = img.copy()
    for x1, y1, x2, y2, s in (d[:5] for d in dets):
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), color, 3)
        cv2.putText(out, f"{s:.2f}", (int(x1), int(y1) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(out, f"{label}: {len(dets)}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--every", type=float, default=0.5, help="샘플 간격(초)")
    ap.add_argument("--out", type=Path, default=Path("output/bench"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    detectors = [
        SCRFD(str(MODELS / "buffalo_l/det_10g.onnx"), 640),
        SCRFD(str(MODELS / "buffalo_l/det_10g.onnx"), 640, use_coreml=False),
        SCRFD(str(MODELS / "buffalo_l/det_10g.onnx"), 1280),
        YuNet(str(MODELS / "yunet.onnx")),
        AppleVision(),
    ]

    for video in args.videos:
        frames = list(sample_frames(video, args.every))
        print(f"\n## {video.name}  ({len(frames)}프레임, 분석 해상도 {frames[0][1].shape[1]}x{frames[0][1].shape[0]})")
        print(f"{'검출기':<14}{'ms/프레임':>10}{'총 검출':>8}{'얼굴 있는 프레임':>16}")
        results = {}
        for det in detectors:
            det.detect(frames[0][1])  # 워밍업
            t0 = time.perf_counter()
            res = [det.detect(img) for _, img in frames]
            ms = (time.perf_counter() - t0) / len(frames) * 1000
            results[det.name] = res
            print(f"{det.name:<14}{ms:>10.1f}{sum(map(len, res)):>8}{sum(len(r) > 0 for r in res):>16}")

        # 비교 이미지: 프레임 6장 x 검출기별 패널 (CPU 버전은 결과가 같아 제외)
        names = [d.name for d in detectors if not d.name.endswith("_cpu")]
        picks = np.linspace(0, len(frames) - 1, 6).astype(int)
        for k, idx in enumerate(picks):
            t, img = frames[idx]
            panels = [draw(img, results[n][idx], COLORS[j], n) for j, n in enumerate(names)]
            panels = [cv2.resize(p, (960, round(960 * p.shape[0] / p.shape[1]))) for p in panels]
            blank = np.zeros_like(panels[0])
            while len(panels) % 2:
                panels.append(blank)
            grid = np.vstack([np.hstack(panels[i:i + 2]) for i in range(0, len(panels), 2)])
            cv2.imwrite(str(args.out / f"{video.stem}_{k}_{t:.1f}s.jpg"), grid, [cv2.IMWRITE_JPEG_QUALITY, 80])


if __name__ == "__main__":
    main()
