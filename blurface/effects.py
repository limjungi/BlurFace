"""얼굴 가리기 효과. 8bit(uint8)와 10bit 처리용(uint16) 이미지를 모두 지원한다."""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np


PAD_X, PAD_TOP, PAD_BOTTOM = 0.15, 0.3, 0.1


def grow(box) -> list[float]:
    """검출 상자는 얼굴만 딱 맞으므로 이마·머리·턱까지 덮게 넓힌다 (실제로 가려지는 영역)."""
    x1, y1, x2, y2 = box[:4]
    bw, bh = x2 - x1, y2 - y1
    return [x1 - bw * PAD_X, y1 - bh * PAD_TOP, x2 + bw * PAD_X, y2 + bh * PAD_BOTTOM]


def shrink(box) -> list[float]:
    """grow의 역: 화면에서 그린 '가릴 영역'을 저장용 얼굴 상자로 바꾼다."""
    x1, y1, x2, y2 = box[:4]
    bw, bh = (x2 - x1) / (1 + 2 * PAD_X), (y2 - y1) / (1 + PAD_TOP + PAD_BOTTOM)
    return [x1 + bw * PAD_X, y1 + bh * PAD_TOP, x2 - bw * PAD_X, y2 - bh * PAD_BOTTOM]


SHAPES = ("rect", "rounded", "ellipse")


def clip_box(box, w: int, h: int):
    x1, y1, x2, y2 = box[:4]
    return max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))


def expand_box(box, w: int, h: int):
    """grow 후 화면 안으로 자른 정수 상자."""
    return clip_box(grow(box), w, h)


def cover_box(box, effect: dict | None = None) -> list[float]:
    """효과의 '범위'(scale, %)까지 반영한 가릴 영역. 화면 밖으로 나갈 수 있음 (모양을 유지하려고 자르지 않음)."""
    x1, y1, x2, y2 = grow(box)
    s = (effect or {}).get("scale", 100) / 100
    if s != 1:
        cx, cy, hw, hh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * s / 2, (y2 - y1) * s / 2
        x1, y1, x2, y2 = cx - hw, cy - hh, cx + hw, cy + hh
    return [x1, y1, x2, y2]


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


def _to_bgra(im: np.ndarray) -> np.ndarray:
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    if im.dtype != np.uint8:
        im = (im / 257).astype(np.uint8)
    return im


@lru_cache(maxsize=32)
def load_frames(path: str) -> tuple[list[np.ndarray], list[float]]:
    """이미지 프레임들(BGRA)과 프레임별 표시 시간(초). 움직이는 GIF는 여러 장, 나머지는 한 장."""
    frames: list[np.ndarray] = []
    durations: list[float] = []
    if path.lower().endswith(".gif"):
        import av
        with av.open(path) as c:
            s = c.streams.video[0]
            tb = float(s.time_base or 0.01)
            last = None
            for f in c.decode(s):
                frames.append(f.to_ndarray(format="bgra"))
                if last is not None and f.pts is not None:
                    durations.append(max(0.02, (f.pts - last) * tb))
                last = f.pts
            if frames:
                durations.append(durations[-1] if durations else 0.1)
    if not frames:
        im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if im is None:
            raise ValueError(f"이미지를 읽을 수 없음: {path}")
        frames, durations = [_to_bgra(im)], [1.0]
    # 투명한 여백을 잘라 내서 보이는 그림이 얼굴 영역을 꽉 채우게 (움직이는 그림은 모든 프레임 기준으로 같게)
    mask = np.zeros(frames[0].shape[:2], bool)
    for f in frames:
        mask |= f[:, :, 3] > 10
    ys, xs = np.nonzero(mask)
    if len(xs):
        frames = [np.ascontiguousarray(f[ys.min():ys.max() + 1, xs.min():xs.max() + 1]) for f in frames]
    return frames, durations


def load_image(path: str, t: float = 0.0) -> np.ndarray:
    """t초 시점의 이미지 (움직이는 GIF는 반복 재생)."""
    frames, durations = load_frames(path)
    if len(frames) == 1:
        return frames[0]
    t %= sum(durations)
    for f, d in zip(frames, durations):
        if t < d:
            return f
        t -= d
    return frames[-1]


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


def _fill(img, box, kind: str, value):
    if kind == "mosaic":
        mosaic(img, box, value or 8)
    elif kind == "blur":
        blur(img, box, value or 30)
    elif kind == "solid":
        solid(img, box, value or "#000000")


def _draw_shape(mask: np.ndarray, box, shape: str):
    x1, y1, x2, y2 = box
    if shape == "ellipse":
        cv2.ellipse(mask, ((x1 + x2) // 2, (y1 + y2) // 2), (max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2)),
                    0, 0, 360, 255, -1, cv2.LINE_AA)
    elif shape == "rounded":
        r = max(1, min(x2 - x1, y2 - y1) // 4)
        cv2.rectangle(mask, (x1 + r, y1), (x2 - r, y2), 255, -1)
        cv2.rectangle(mask, (x1, y1 + r), (x2, y2 - r), 255, -1)
        for cx, cy in ((x1 + r, y1 + r), (x2 - r, y1 + r), (x1 + r, y2 - r), (x2 - r, y2 - r)):
            cv2.circle(mask, (cx, cy), r, 255, -1, cv2.LINE_AA)
    else:
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)


def apply(img: np.ndarray, box, effect: dict, t: float = 0.0):
    """box는 가릴 영역 (화면 밖으로 나가도 됨).

    t: 영상 시각(초). 움직이는 GIF 스티커의 프레임을 고르는 데 씀.
    effect 추가 옵션: shape(rect|rounded|ellipse), feather(가장자리 부드럽게, 상자 짧은 변의 %), scale(범위 %, cover_box에서 반영)
    """
    h, w = img.shape[:2]
    full = [int(round(v)) for v in box[:4]]
    c = clip_box(full, w, h)
    if c[2] - c[0] < 2 or c[3] - c[1] < 2:
        return
    kind, value = effect["type"], effect.get("value")
    if kind == "none":
        return
    if kind in ("sticker", "image"):
        # under: 그림의 투명한 틈(하트 모양 바깥 등)으로 얼굴이 보이지 않게 아래를 먼저 흐림.
        # 기본 스티커는 켜짐, 내 이미지는 꺼짐 (이미지만 깔끔하게 보이도록)
        if effect.get("under", kind == "sticker"):
            blur(img, c, 60)
        overlay(img, full, builtin_sticker(value or "smile") if kind == "sticker" else load_image(value, t))
        return
    shape = effect.get("shape", "rect")
    f = int(min(full[2] - full[0], full[3] - full[1]) * effect.get("feather", 0) / 100)
    if shape == "rect" and f == 0:
        _fill(img, c, kind, value)
        return
    # 모양·부드러운 가장자리: 넓힌 영역 전체에 효과를 낸 뒤 모양 마스크로 원본과 섞는다.
    # 가장자리를 흐려도 원래 영역은 빠짐없이 덮도록 모양을 f만큼 키우고 바깥쪽으로 2f에 걸쳐 흐려지게 한다.
    x1, y1, x2, y2 = region = clip_box([full[0] - 2 * f, full[1] - 2 * f, full[2] + 2 * f, full[3] + 2 * f], w, h)
    orig = img[y1:y2, x1:x2].copy()
    # 넓힌 영역에서도 블록 크기·흐림 정도가 원래 영역 기준과 같도록 보정
    k = max(x2 - x1, y2 - y1) / max(1, full[2] - full[0], full[3] - full[1])
    if kind == "mosaic":
        value = (value or 8) * k
    elif kind == "blur":
        value = (value or 30) / k
    _fill(img, region, kind, value)
    mask = np.zeros((y2 - y1, x2 - x1), np.uint8)
    _draw_shape(mask, [full[0] - f - x1, full[1] - f - y1, full[2] + f - x1, full[3] + f - y1], shape)
    if f:
        mask = cv2.blur(mask, (2 * f + 1, 2 * f + 1))
    roi = img[y1:y2, x1:x2]
    m = mask.astype(np.float32) / 255
    if img.dtype == np.uint8:  # 8bit는 OpenCV로 섞는 게 몇 배 빠름
        roi[:] = cv2.blendLinear(roi, orig, m, 1 - m)
    else:
        m = m[..., None]
        roi[:] = np.rint(roi.astype(np.float32) * m + orig.astype(np.float32) * (1 - m)).astype(img.dtype)
