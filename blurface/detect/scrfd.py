"""SCRFD (InsightFace det_10g) ONNX 검출기."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from . import Detector, nms

STRIDES = (8, 16, 32)
NUM_ANCHORS = 2


def fixed_size_model(model_path: str, size: int) -> str:
    """입력 크기를 고정한 모델 사본을 만든다. 원본은 출력 크기가 640 기준으로 박혀 있어 CoreML에서 다른 크기가 실패한다."""
    src = Path(model_path)
    dst = src.with_name(f"{src.stem}_{size}{src.suffix}")
    if dst.exists():
        return str(dst)
    import onnx

    m = onnx.load(str(src))
    dims = m.graph.input[0].type.tensor_type.shape.dim
    for d, v in zip(dims, (1, 3, size, size)):
        d.ClearField("dim_param")
        d.dim_value = v
    for o in m.graph.output:
        for i, d in enumerate(o.type.tensor_type.shape.dim):
            d.ClearField("dim_value")
            d.dim_param = f"{o.name}_{i}"
    onnx.save(m, str(dst))
    return str(dst)


class SCRFD(Detector):
    def __init__(self, model_path: str, input_size: int = 640, score_thresh: float = 0.5,
                 nms_thresh: float = 0.4, use_coreml: bool = True):
        providers = ["CPUExecutionProvider"]
        if use_coreml:
            providers.insert(0, "CoreMLExecutionProvider")
            model_path = fixed_size_model(model_path, input_size)
        self.session = ort.InferenceSession(model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.size = input_size
        self.score_thresh = score_thresh
        self.nms_thresh = nms_thresh
        self.name = f"scrfd{input_size}" + ("" if use_coreml else "_cpu")
        self._centers: dict[int, np.ndarray] = {}

    def _anchor_centers(self, stride: int) -> np.ndarray:
        if stride not in self._centers:
            n = self.size // stride
            ys, xs = np.mgrid[:n, :n]
            c = (np.stack([xs, ys], axis=-1).reshape(-1, 2) * stride).astype(np.float32)
            self._centers[stride] = np.repeat(c, NUM_ANCHORS, axis=0)
        return self._centers[stride]

    def detect(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        scale = self.size / max(h, w)
        resized = cv2.resize(bgr, (round(w * scale), round(h * scale)))
        canvas = np.zeros((self.size, self.size, 3), np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        blob = cv2.dnn.blobFromImage(canvas, 1 / 128, (self.size, self.size),
                                     (127.5, 127.5, 127.5), swapRB=True)
        outs = self.session.run(None, {self.input_name: blob})
        n = len(STRIDES)
        boxes = []
        for i, stride in enumerate(STRIDES):
            scores = outs[i].reshape(-1)
            dist = outs[i + n].reshape(-1, 4) * stride
            keep = scores >= self.score_thresh
            if not keep.any():
                continue
            c = self._anchor_centers(stride)[keep]
            d = dist[keep]
            kps = outs[i + 2 * n].reshape(-1, 10)[keep] * stride
            kps = kps + np.tile(c, 5)  # 키포인트 5개(눈·코·입꼬리)는 앵커 중심 기준 오프셋
            b = np.stack([c[:, 0] - d[:, 0], c[:, 1] - d[:, 1],
                          c[:, 0] + d[:, 2], c[:, 1] + d[:, 3], scores[keep]], axis=1)
            boxes.append(np.hstack([b, kps]))
        if not boxes:
            return np.zeros((0, 15), np.float32)
        dets = np.concatenate(boxes)
        dets[:, :4] /= scale
        dets[:, 5:] /= scale
        return nms(dets, self.nms_thresh)
