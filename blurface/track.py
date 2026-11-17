"""ByteTrack 방식의 간단한 얼굴 추적기.

- 높은 점수 검출을 먼저 기존 트랙에 붙이고, 남은 트랙에 낮은 점수 검출을 붙인다 (가려짐·흐림 대응)
- 등속 예측으로 빠르게 움직이는 얼굴을 따라간다
- 컷마다 새 Tracker를 만들어 장면 사이에 상자가 이어지지 않게 한다
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda r: (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1])  # noqa: E731
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


@dataclass
class Track:
    id: int
    box: np.ndarray  # 마지막 관측 x1,y1,x2,y2
    last_frame: int
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(4))
    hits: int = 1
    observations: dict[int, tuple[float, float, float, float, float]] = field(default_factory=dict)

    def predict(self, frame: int) -> np.ndarray:
        return self.box + self.velocity * (frame - self.last_frame)

    def update(self, frame: int, det: np.ndarray):
        dt = max(1, frame - self.last_frame)
        v = (det[:4] - self.box) / dt
        self.velocity = 0.6 * self.velocity + 0.4 * v if self.hits > 1 else v * 0.5
        self.box = det[:4].copy()
        self.last_frame = frame
        self.hits += 1
        self.observations[frame] = tuple(float(x) for x in det[:5])


class Tracker:
    def __init__(self, next_id: int = 0, high: float = 0.6, low: float = 0.3,
                 match_iou: float = 0.15, max_lost: int = 30):
        self.next_id = next_id
        self.high, self.low = high, low
        self.match_iou = match_iou
        self.max_lost = max_lost
        self.active: list[Track] = []
        self.finished: list[Track] = []

    def _match(self, tracks: list[Track], dets: np.ndarray, frame: int):
        if not tracks or len(dets) == 0:
            return [], list(range(len(tracks))), list(range(len(dets)))
        preds = np.stack([t.predict(frame) for t in tracks])
        iou = iou_matrix(preds, dets[:, :4])
        rows, cols = linear_sum_assignment(-iou)
        pairs = [(r, c) for r, c in zip(rows, cols) if iou[r, c] >= self.match_iou]
        mr = {r for r, _ in pairs}
        mc = {c for _, c in pairs}
        return pairs, [i for i in range(len(tracks)) if i not in mr], [j for j in range(len(dets)) if j not in mc]

    def update(self, frame: int, dets: np.ndarray):
        dets = dets[dets[:, 4] >= self.low] if len(dets) else dets
        high = dets[dets[:, 4] >= self.high] if len(dets) else dets
        low = dets[dets[:, 4] < self.high] if len(dets) else dets

        pairs, un_t, un_d = self._match(self.active, high, frame)
        for r, c in pairs:
            self.active[r].update(frame, high[c])
        remaining = [self.active[i] for i in un_t]
        pairs2, un_t2, _ = self._match(remaining, low, frame)
        for r, c in pairs2:
            remaining[r].update(frame, low[c])

        for j in un_d:
            t = Track(self.next_id, high[j][:4].copy(), frame)
            t.observations[frame] = tuple(float(x) for x in high[j][:5])
            self.next_id += 1
            self.active.append(t)

        still = []
        for t in self.active:
            (self.finished if frame - t.last_frame > self.max_lost else still).append(t)
        self.active = still

    def close(self) -> list[Track]:
        self.finished.extend(self.active)
        self.active = []
        return self.finished
