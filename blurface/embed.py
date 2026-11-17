"""ArcFace 얼굴 특징값(512차원). 같은 사람이면 코사인 유사도가 높다."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from .detect.scrfd import fixed_size_model

MODELS = Path(__file__).resolve().parents[1] / "models"

# ArcFace 112x112 정렬 기준 위치 (왼눈, 오른눈, 코, 왼입꼬리, 오른입꼬리)
TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                     [41.5493, 92.3655], [70.7299, 92.2041]], np.float32)


class ArcFace:
    def __init__(self, model_path: str | None = None):
        path = model_path or str(MODELS / "buffalo_l/w600k_r50.onnx")
        path = fixed_size_model(path, 112)
        self.session = ort.InferenceSession(path, providers=["CoreMLExecutionProvider", "CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    @staticmethod
    def align(bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        m, _ = cv2.estimateAffinePartial2D(kps.reshape(5, 2).astype(np.float32), TEMPLATE, method=cv2.LMEDS)
        return cv2.warpAffine(bgr, m, (112, 112), borderValue=0)

    def embed(self, bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        face = self.align(bgr, kps)
        blob = cv2.dnn.blobFromImage(face, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        v = self.session.run(None, {self.input_name: blob})[0][0]
        return v / (np.linalg.norm(v) + 1e-9)
