"""얼굴 검출기. 모든 검출기는 BGR 이미지를 받아 (N, 5 이상) 배열 [x1, y1, x2, y2, score, (키포인트 10개)]를 돌려준다."""

from __future__ import annotations

import numpy as np


class Detector:
    name = "base"

    def detect(self, bgr: np.ndarray) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError


def nms(dets: np.ndarray, thresh: float) -> np.ndarray:
    """점수 순으로 겹치는 상자를 제거한다."""
    if len(dets) == 0:
        return dets
    x1, y1, x2, y2, s = dets[:, :5].T
    areas = (x2 - x1) * (y2 - y1)
    order = s.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= thresh]
    return dets[keep]
