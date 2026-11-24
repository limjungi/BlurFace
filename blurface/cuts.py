"""컷(장면 전환) 감지.

진짜 컷은 한 프레임에서만 변화량이 튀고, 빠른 움직임은 여러 프레임 동안 계속 크게 변한다.
그래서 "변화량이 충분히 크고, 앞뒤 프레임보다 몇 배 이상 큰" 프레임만 컷으로 본다.
검출과 같은 디코딩 패스에서 프레임마다 작은 특징값만 뽑아 두고, 끝난 뒤 한 번에 판단한다.
"""

from __future__ import annotations

import cv2
import numpy as np


def signature(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = bgr.shape[:2]
    if w % 128 or h % 72:  # 정수 배가 아니면 INTER_AREA가 아주 느려서(정사각·세로 영상) 먼저 정수 배 크기로 맞춤
        bgr = cv2.resize(bgr, (128 * max(1, w // 128), 72 * max(1, h // 72)), interpolation=cv2.INTER_LINEAR)
    small = cv2.resize(bgr, (128, 72), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hs = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256]).ravel()
    v = cv2.calcHist([hsv], [2], None, [16], [0, 256]).ravel()
    hist = np.concatenate([hs / max(hs.sum(), 1), v / max(v.sum(), 1)])
    thumb = cv2.resize(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (32, 18)).astype(np.float32)
    return hist, thumb


def differences(sigs: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    d = np.zeros(len(sigs))
    for i in range(1, len(sigs)):
        (h0, t0), (h1, t1) = sigs[i - 1], sigs[i]
        d[i] = 0.5 * np.abs(h1 - h0).sum() + np.abs(t1 - t0).mean() / 255
    return d


def find_cuts(d: np.ndarray, min_diff: float = 0.3, min_ratio: float = 4.0, window: int = 2,
              min_gap: int = 5) -> list[int]:
    cuts: list[int] = []
    for i in range(1, len(d)):
        if d[i] < min_diff:
            continue
        nb = np.r_[d[max(1, i - window):i], d[i + 1:i + 1 + window]]
        if len(nb) and d[i] / (nb.max() + 1e-3) < min_ratio:
            continue
        if cuts and i - cuts[-1] < min_gap:
            continue
        cuts.append(i)
    return cuts
