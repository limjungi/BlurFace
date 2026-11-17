"""Apple Vision 프레임워크 얼굴 검출기 (macOS 전용)."""

from __future__ import annotations

import cv2
import numpy as np
import Quartz
import Vision
from Foundation import NSData

from . import Detector


def _to_cgimage(bgr: np.ndarray):
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
    h, w = rgba.shape[:2]
    data = NSData.dataWithBytes_length_(rgba.tobytes(), rgba.nbytes)
    provider = Quartz.CGDataProviderCreateWithCFData(data)
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, Quartz.CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGImageAlphaNoneSkipLast, provider, None, False, Quartz.kCGRenderingIntentDefault)


class AppleVision(Detector):
    name = "vision"

    def __init__(self, max_side: int = 1920):
        self.max_side = max_side

    def detect(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        scale = min(1.0, self.max_side / max(h, w))
        img = cv2.resize(bgr, (round(w * scale), round(h * scale))) if scale < 1 else bgr
        request = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(_to_cgimage(img), None)
        ok, _ = handler.performRequests_error_([request], None)
        if not ok or not request.results():
            return np.zeros((0, 5), np.float32)
        out = []
        for obs in request.results():
            (x, y), (bw, bh) = obs.boundingBox()
            # Vision 좌표는 0~1 정규화, 원점이 왼쪽 아래
            out.append([x * w, (1 - y - bh) * h, (x + bw) * w, (1 - y) * h, obs.confidence()])
        return np.asarray(out, np.float32)
