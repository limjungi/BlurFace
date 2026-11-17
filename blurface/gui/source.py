"""미리보기용 프레임 읽기: 원하는 프레임으로 이동(seek)과 순차 재생을 모두 지원, 축소 해상도."""

from __future__ import annotations

import bisect

import av
import cv2
import numpy as np

from ..video import ROTATE, VideoInfo


class FrameSource:
    def __init__(self, info: VideoInfo, max_side: int = 1280):
        self.info = info
        self.container = av.open(info.path)
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = "AUTO"
        self.tb = float(self.stream.time_base)
        k = min(1.0, max_side / max(info.width, info.height))
        cw, ch = self.stream.codec_context.width, self.stream.codec_context.height
        self.size = (max(2, round(cw * k) // 2 * 2), max(2, round(ch * k) // 2 * 2))
        self.pts: list[float] = []
        self.pos = -1
        self._frame = None
        self._image: np.ndarray | None = None
        self._it = self.container.decode(self.stream)
        first = next(self._it)
        self.t0 = float((first.pts or 0) * self.tb)
        self._seek_to_time(self.t0)
        dw = self.size[1] if info.rotation in (90, 270) else self.size[0]
        self.scale = dw / info.width  # 원본 좌표 → 미리보기 좌표

    def set_pts(self, pts: list[float]):
        self.pts = pts

    def close(self):
        self.container.close()

    def _index_of(self, t: float) -> int:
        rel = t - self.t0
        if self.pts:
            return min(len(self.pts) - 1, bisect.bisect_left(self.pts, rel - 1e-4))
        return int(round(rel * self.info.fps))

    def _time_of(self, idx: int) -> float:
        if self.pts and 0 <= idx < len(self.pts):
            return self.pts[idx] + self.t0
        return idx / self.info.fps + self.t0

    def _seek_to_time(self, t: float):
        self.container.seek(max(0, int(t / self.tb)), stream=self.stream, backward=True)
        self._it = self.container.decode(self.stream)
        self.pos = -1

    def read(self, idx: int) -> np.ndarray | None:
        """프레임 idx의 BGR 이미지 (보이는 방향, 축소). 가까운 앞쪽이면 순차 디코딩, 아니면 이동."""
        idx = max(0, idx)
        if idx == self.pos and self._image is not None:
            return self._image
        if not (self.pos < idx <= self.pos + 60):
            self._seek_to_time(self._time_of(idx))
        frame = None
        while self.pos < idx:
            try:
                frame = next(self._it)
            except (StopIteration, av.error.EOFError):
                break
            self.pos = self._index_of(float((frame.pts or 0) * self.tb))
        if frame is not None:
            img = frame.to_ndarray(format="bgr24", width=self.size[0], height=self.size[1])
            if self.info.rotation:
                img = cv2.rotate(img, ROTATE[self.info.rotation])
            self._image = np.ascontiguousarray(img)
        return self._image
