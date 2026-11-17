"""트랙을 인물로 묶기와 인물 얼굴 목록 이미지 만들기."""

from __future__ import annotations

import av
import cv2
import numpy as np

from .video import ROTATE


def cluster_tracks(embs: dict[int, np.ndarray | None], frames: dict[int, set[int]],
                   threshold: float = 0.35) -> dict[int, int]:
    """평균 연결 군집화. 같은 프레임에 함께 나온 트랙은 같은 사람일 수 없다(cannot-link).

    반환: 트랙 id -> 인물 id (0부터, 등장 순서)
    """
    tids = sorted(embs)
    clusters: list[list[int]] = [[t] for t in tids]
    cframes: list[set[int]] = [set(frames[t]) for t in tids]

    def sim(a: list[int], b: list[int]) -> float:
        va = [embs[t] for t in a if embs[t] is not None]
        vb = [embs[t] for t in b if embs[t] is not None]
        if not va or not vb:
            return -1.0
        return float(np.mean(np.stack(va) @ np.stack(vb).T))

    while True:
        best, pair = threshold, None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if cframes[i] & cframes[j]:
                    continue
                s = sim(clusters[i], clusters[j])
                if s > best:
                    best, pair = s, (i, j)
        if pair is None:
            break
        i, j = pair
        clusters[i] += clusters.pop(j)
        cframes[i] |= cframes.pop(j)

    first = {i: min(min(frames[t]) for t in c) for i, c in enumerate(clusters)}
    order = sorted(range(len(clusters)), key=first.get)
    return {t: pid for pid, ci in enumerate(order) for t in clusters[ci]}


def grab_frames(info, wanted: set[int]) -> dict[int, np.ndarray]:
    """필요한 프레임만 원본 해상도로 꺼낸다 (순차 디코딩, 마지막 필요한 프레임에서 멈춤)."""
    out: dict[int, np.ndarray] = {}
    if not wanted:
        return out
    last = max(wanted)
    with av.open(info.path) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        for i, frame in enumerate(c.decode(s)):
            if i in wanted:
                img = frame.to_ndarray(format="bgr24")
                out[i] = cv2.rotate(img, ROTATE[info.rotation]) if info.rotation else img
            if i >= last:
                break
    return out


def face_crop(img: np.ndarray, box, size: int = 160) -> np.ndarray:
    x1, y1, x2, y2 = box
    cx, cy, r = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1) * 0.8
    h, w = img.shape[:2]
    a, b = int(max(0, cx - r)), int(max(0, cy - r))
    crop = img[b:int(min(h, cy + r)), a:int(min(w, cx + r))]
    return cv2.resize(crop, (size, size)) if crop.size else np.zeros((size, size, 3), np.uint8)


def contact_sheet(crops: list[tuple[str, str, np.ndarray]], cols: int = 6) -> np.ndarray:
    """(제목, 부제, 얼굴) 목록 → 격자 이미지."""
    tiles = []
    for title, sub, face in crops:
        tile = np.full((210, 170, 3), 32, np.uint8)
        tile[5:165, 5:165] = face
        cv2.putText(tile, title, (8, 186), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(tile, sub, (8, 204), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 255), 1)
        tiles.append(tile)
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 32))
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
