"""얼굴 가리기 효과. 8bit(uint8)와 10bit 처리용(uint16) 이미지를 모두 지원한다."""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np


def expand_box(box, w: int, h: int, pad_x: float = 0.15, pad_top: float = 0.3, pad_bottom: float = 0.1):
    """검출 상자는 얼굴만 딱 맞으므로 이마·머리·턱까지 덮게 넓힌다."""
    x1, y1, x2, y2 = box[:4]
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - bw * pad_x)), max(0, int(y1 - bh * pad_top)),
            min(w, int(x2 + bw * pad_x)), min(h, int(y2 + bh * pad_bottom)))


def _max(img: np.ndarray) -> int:
    return 65535 if img.dtype == np.uint16 else 255


def mosaic(img, box, blocks: float = 8):
    x1, y1, x2, y2 = box
    roi = img[y1:y2, x1:x2]
    rw, rh = roi.shape[1], roi.shape[0]
    bs = max(4, int(rw / max(2, blocks)))
    small = cv2.resize(roi, (max(1, round(rw / bs)), max(1, round(rh / bs))), interpolation=cv2.INTER_AREA)
    img[y1:y2, x1:x2] = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)


def blur(img, box, strength: float = 30):
    x1, y1, x2, y2 = box
    roi = img[y1:y2, x1:x2]
    rh, rw = roi.shape[:2]
    # 강한 블러는 작게 줄여 흐린 뒤 키워도 결과가 같고 훨씬 빠르다 (큰 얼굴에서 수십 배)
    k = min(1.0, 64 / max(rh, rw))
    small = cv2.resize(roi, (max(1, round(rw * k)), max(1, round(rh * k))), interpolation=cv2.INTER_AREA)
    ks = max(3, int(max(small.shape[:2]) * strength / 100)) | 1
    small = cv2.GaussianBlur(cv2.GaussianBlur(small, (ks, ks), 0), (ks, ks), 0)
    img[y1:y2, x1:x2] = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_LINEAR)


def solid(img, box, color: str = "#000000"):
    x1, y1, x2, y2 = box
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    scale = _max(img) / 255
    img[y1:y2, x1:x2] = (b * scale, g * scale, r * scale)


@lru_cache(maxsize=16)
def builtin_sticker(name: str) -> np.ndarray:
    """기본 스티커 (BGRA 256x256)."""
    s = np.zeros((256, 256, 4), np.uint8)
    if name == "heart":
        pts = np.array([[128, 230], [20, 110], [30, 50], [80, 30], [128, 70], [176, 30], [226, 50], [236, 110]])
        cv2.fillPoly(s, [pts], (80, 60, 230, 255), cv2.LINE_AA)
        cv2.circle(s, (78, 78), 52, (80, 60, 230, 255), -1, cv2.LINE_AA)
        cv2.circle(s, (178, 78), 52, (80, 60, 230, 255), -1, cv2.LINE_AA)
    else:  # smile
        cv2.circle(s, (128, 128), 124, (40, 200, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(s, (128, 128), 124, (20, 120, 200, 255), 6, cv2.LINE_AA)
        cv2.ellipse(s, (88, 100), (14, 22), 0, 0, 360, (40, 40, 40, 255), -1, cv2.LINE_AA)
        cv2.ellipse(s, (168, 100), (14, 22), 0, 0, 360, (40, 40, 40, 255), -1, cv2.LINE_AA)
        cv2.ellipse(s, (128, 140), (64, 52), 0, 20, 160, (40, 40, 40, 255), 10, cv2.LINE_AA)
    return s


@lru_cache(maxsize=32)
def load_image(path: str) -> np.ndarray:
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise ValueError(f"이미지를 읽을 수 없음: {path}")
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    return im


def overlay(img, box, rgba: np.ndarray):
    """상자를 완전히 덮도록(비율 유지, 넘치는 부분은 화면 안에서 잘림) 이미지를 얹는다."""
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    h, w = img.shape[:2]
    k = max(bw / rgba.shape[1], bh / rgba.shape[0]) * 1.05
    sw, sh = max(1, round(rgba.shape[1] * k)), max(1, round(rgba.shape[0] * k))
    st = cv2.resize(rgba, (sw, sh), interpolation=cv2.INTER_AREA)
    ox, oy = x1 + (bw - sw) // 2, y1 + (bh - sh) // 2
    a, b = max(0, ox), max(0, oy)
    c, d = min(w, ox + sw), min(h, oy + sh)
    if c <= a or d <= b:
        return
    st = st[b - oy:d - oy, a - ox:c - ox]
    alpha = st[:, :, 3:4].astype(np.float32) / 255
    color = st[:, :, :3].astype(np.float32) * (_max(img) / 255)
    roi = img[b:d, a:c].astype(np.float32)
    img[b:d, a:c] = (color * alpha + roi * (1 - alpha)).astype(img.dtype)


def apply(img: np.ndarray, box, effect: dict):
    """box는 expand_box를 거친 정수 상자."""
    x1, y1, x2, y2 = box
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    kind, value = effect["type"], effect.get("value")
    if kind == "mosaic":
        mosaic(img, box, value or 8)
    elif kind == "blur":
        blur(img, box, value or 30)
    elif kind == "solid":
        solid(img, box, value or "#000000")
    elif kind in ("sticker", "image"):
        # 스티커의 투명한 틈(하트 모양 바깥 등)으로 얼굴이 보이지 않도록 먼저 강하게 흐린 뒤 얹는다
        blur(img, box, 60)
        overlay(img, box, builtin_sticker(value or "smile") if kind == "sticker" else load_image(value))
