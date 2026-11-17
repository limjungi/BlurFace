"""영상 분석: 컷 감지 → 프레임별 얼굴 검출 → 컷 단위 추적 → 빈 구간 채우기·떨림 보정."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import av
import cv2
import numpy as np
from scenedetect import AdaptiveDetector, detect

from .detect.scrfd import SCRFD
from .track import Tracker

MODELS = Path(__file__).resolve().parents[1] / "models"


@dataclass
class Analysis:
    width: int
    height: int
    fps: float
    n_frames: int
    cuts: list[int]
    # track_id -> {frame: (x1, y1, x2, y2, score, source)}  좌표는 원본 해상도 기준
    tracks: dict[int, dict[int, tuple]] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)


def detect_cuts(path: Path) -> list[int]:
    scenes = detect(str(path), AdaptiveDetector(), backend="pyav")
    return [s[0].get_frames() for s in scenes[1:]]


def iter_frames(path: Path, max_side: int):
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        for frame in c.decode(s):
            img = frame.to_ndarray(format="bgr24")
            h, w = img.shape[:2]
            k = min(1.0, max_side / max(h, w))
            if k < 1:
                img = cv2.resize(img, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
            yield img, k


def _fill_and_smooth(obs: dict[int, tuple], max_gap: int, extend: int, lo: int, hi: int, window: int = 5):
    frames = sorted(obs)
    out: dict[int, tuple] = {f: (*obs[f][:5], "auto") for f in frames}
    # 관측 사이 빈 프레임은 선형 보간
    for a, b in zip(frames, frames[1:]):
        if 1 < b - a <= max_gap:
            pa, pb = np.array(obs[a][:4]), np.array(obs[b][:4])
            for f in range(a + 1, b):
                t = (f - a) / (b - a)
                out[f] = (*(pa + (pb - pa) * t), min(obs[a][4], obs[b][4]), "interp")
    # 앞뒤로 몇 프레임 늘려 검출이 늦게 시작·일찍 끝날 때 얼굴이 드러나지 않게 함 (같은 컷 안에서만)
    first, last = frames[0], frames[-1]
    for f in range(max(lo, first - extend), first):
        out[f] = (*obs[first][:5], "interp")
    for f in range(last + 1, min(hi, last + extend + 1)):
        out[f] = (*obs[last][:5], "interp")
    # 이동 평균으로 떨림 보정 (연속 구간 안에서만)
    keys = sorted(out)
    arr = np.array([out[f][:4] for f in keys])
    half = window // 2
    smoothed = arr.copy()
    for i in range(len(keys)):
        j0, j1 = i, i
        while j0 > max(0, i - half) and keys[j0 - 1] == keys[j0] - 1:
            j0 -= 1
        while j1 < min(len(keys) - 1, i + half) and keys[j1 + 1] == keys[j1] + 1:
            j1 += 1
        smoothed[i] = arr[j0:j1 + 1].mean(axis=0)
    return {f: (*smoothed[i], out[f][4], out[f][5]) for i, f in enumerate(keys)}


def analyze(path: Path, max_side: int = 1920, progress=None) -> Analysis:
    path = Path(path)
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        width, height = s.codec_context.width, s.codec_context.height
        fps = float(s.average_rate)
        n_frames = s.frames or 0

    timings = {}
    t0 = time.perf_counter()
    cuts = detect_cuts(path)
    timings["cuts"] = time.perf_counter() - t0

    detector = SCRFD(str(MODELS / "buffalo_l/det_10g.onnx"), 640, score_thresh=0.3)
    max_lost = max(5, round(fps * 0.5))
    tracker, next_id, finished = Tracker(max_lost=max_lost), 0, []
    bounds = [0, *cuts]  # 각 컷 시작 프레임
    shot_of = {}
    cut_set = set(cuts)

    t0 = time.perf_counter()
    frame_idx = -1
    for frame_idx, (img, k) in enumerate(iter_frames(path, max_side)):
        if frame_idx in cut_set:
            finished += tracker.close()
            next_id = tracker.next_id
            tracker = Tracker(next_id=next_id, max_lost=max_lost)
        dets = detector.detect(img)
        if len(dets):
            dets[:, :4] /= k
        tracker.update(frame_idx, dets)
        if progress and frame_idx % 50 == 0:
            progress(frame_idx, n_frames)
    finished += tracker.close()
    n_frames = frame_idx + 1
    timings["detect_track"] = time.perf_counter() - t0

    bounds.append(n_frames)
    tracks = {}
    for t in finished:
        scores = [o[4] for o in t.observations.values()]
        # 짧고 점수 낮은 트랙은 오검출로 보고 버림
        if len(scores) < 3 and max(scores) < 0.7:
            continue
        first = min(t.observations)
        lo = max(b for b in bounds if b <= first)
        hi = min(b for b in bounds if b > first)
        shot_of[t.id] = lo
        tracks[t.id] = _fill_and_smooth(t.observations, max_gap=max_lost, extend=2, lo=lo, hi=hi)

    return Analysis(width, height, fps, n_frames, cuts, tracks, timings)
