"""YuNet (OpenCV) 검출기."""

from __future__ import annotations

import cv2
import numpy as np

from . import Detector


class YuNet(Detector):
    name = "yunet"

    def __init__(self, model_path: str, score_thresh: float = 0.6, max_side: int = 1280):
        self.model = cv2.FaceDetectorYN.create(model_path, "", (320, 320), score_thresh, 0.3, 5000)
        self.max_side = max_side

    def detect(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        scale = min(1.0, self.max_side / max(h, w))
        img = cv2.resize(bgr, (round(w * scale), round(h * scale))) if scale < 1 else bgr
        self.model.setInputSize((img.shape[1], img.shape[0]))
        _, faces = self.model.detect(img)
        if faces is None:
            return np.zeros((0, 5), np.float32)
        x, y, fw, fh = faces[:, 0], faces[:, 1], faces[:, 2], faces[:, 3]
        dets = np.stack([x / scale, y / scale, (x + fw) / scale, (y + fh) / scale, faces[:, 14]], axis=1)
        return dets.astype(np.float32)
