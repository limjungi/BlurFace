"""화면 부품: 영상 표시, 타임라인, 효과 선택."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QColorDialog, QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSpinBox, QStackedWidget, QWidget)



EFFECT_CHOICES = [("모자이크", "mosaic"), ("블러", "blur"), ("단색", "solid"), ("스티커", "sticker"),
                  ("내 이미지", "image"), ("가리지 않음", "none")]
EFFECT_COLORS = {"mosaic": "#5b8def", "blur": "#7a6ff0", "solid": "#555b66", "sticker": "#f0b429",
                 "image": "#3ebd93", "none": "#e5534b"}
STICKERS = [("스마일", "smile"), ("하트", "heart")]


def effect_text(e: dict | None) -> str:
    if e is None:
        return "기본 효과"
    names = dict((v, k) for k, v in EFFECT_CHOICES)
    label = names.get(e["type"], e["type"])
    v = e.get("value")
    if e["type"] == "sticker":
        return f"{label}·{dict((b, a) for a, b in STICKERS).get(v, v)}"
    if e["type"] == "image" and v:
        return f"{label}·{v.rsplit('/', 1)[-1]}"
    if e["type"] in ("mosaic", "blur", "solid") and v:
        return f"{label} {int(v) if e['type'] != 'solid' else v}"
    return label


BOX_COLORS = {"auto": "#3ebd93", "interp": "#4fc3f7", "manual": "#e05cd6"}
HANDLE = 7  # 모서리 손잡이 반경(화면 px)


class VideoView(QWidget):
    """BGR 이미지를 비율 유지해 가운데 표시. edit이면 상자를 보여주고 선택·이동·크기 조절·새로 그리기.

    상자 좌표는 모두 원본 영상 해상도 기준 '실제로 가려지는 영역'.
    """

    box_clicked = Signal(object)  # 트랙 번호 또는 None(빈 곳 클릭)
    box_changed = Signal(int, list)  # 트랙 번호, 새 영역
    box_drawn = Signal(list)  # 새로 그린 영역

    def __init__(self):
        super().__init__()
        self._pix: QPixmap | None = None
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.message = "영상을 열어 주세요 (⌘O 또는 끌어다 놓기)"
        self.video_size = (1, 1)  # 원본 해상도 (상자 좌표 기준)
        self.edit = False
        self.boxes: list[tuple[int, str, list[float], str]] = []  # (트랙, 이름표, 영역, 출처)
        self.selected: int | None = None
        self._drag: dict | None = None
        self.setMouseTracking(True)

    def set_image(self, img: np.ndarray | None):
        if img is None:
            self._pix = None
        else:
            h, w = img.shape[:2]
            qimg = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888)
            self._pix = QPixmap.fromImage(qimg.copy())
        self.update()

    def set_boxes(self, boxes, selected: int | None):
        if self._drag:  # 끄는 중에는 화면 갱신으로 덮어쓰지 않음
            return
        self.boxes, self.selected = boxes, selected
        self.update()

    # 좌표 변환
    def _area(self) -> QRectF:
        if self._pix is None:
            return QRectF(self.rect())
        size = self._pix.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                      size.width(), size.height())

    def _k(self) -> float:
        return self._area().width() / max(1, self.video_size[0])

    def to_screen(self, b) -> QRectF:
        a, k = self._area(), self._k()
        return QRectF(a.x() + b[0] * k, a.y() + b[1] * k, (b[2] - b[0]) * k, (b[3] - b[1]) * k)

    def to_video(self, pt: QPointF) -> tuple[float, float]:
        a, k = self._area(), self._k()
        w, h = self.video_size
        return (min(w, max(0.0, (pt.x() - a.x()) / k)), min(h, max(0.0, (pt.y() - a.y()) / k)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111317"))
        if self._pix is None:
            p.setPen(QColor("#8b929e"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self._area(), self._pix, QRectF(self._pix.rect()))
        if not self.edit:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for tid, text, b, src in self.boxes:
            r = self.to_screen(b)
            sel = tid == self.selected
            color = QColor("#ffd23f" if sel else BOX_COLORS.get(src, "#ffffff"))
            p.setPen(QPen(color, 3 if sel else 2, Qt.PenStyle.SolidLine if src != "interp" else Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            p.fillRect(QRectF(r.x(), r.y() - 18, max(34, len(text) * 8 + 8), 18), color)
            p.setPen(QColor("#111"))
            p.drawText(QRectF(r.x() + 4, r.y() - 18, 200, 18), Qt.AlignmentFlag.AlignVCenter, text)
            if sel:
                p.setBrush(color)
                for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                    p.drawEllipse(c, HANDLE - 2, HANDLE - 2)
        if self._drag and self._drag["mode"] == "new":
            p.setPen(QPen(QColor("#ffd23f"), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.to_screen(self._drag["box"]))

    # 마우스
    def _hit(self, pt: QPointF) -> tuple[int | None, str | None]:
        """(트랙, 모드). 선택된 상자의 모서리 → 크기 조절, 상자 안 → 이동."""
        for tid, _t, b, _s in self.boxes:
            if tid != self.selected:
                continue
            r = self.to_screen(b)
            for mode, c in (("tl", r.topLeft()), ("tr", r.topRight()), ("bl", r.bottomLeft()), ("br", r.bottomRight())):
                if abs(pt.x() - c.x()) <= HANDLE + 2 and abs(pt.y() - c.y()) <= HANDLE + 2:
                    return tid, mode
        # 작은 상자가 큰 상자 안에 있을 수 있으니 작은 것부터
        for tid, _t, b, _s in sorted(self.boxes, key=lambda x: (x[2][2] - x[2][0]) * (x[2][3] - x[2][1])):
            if self.to_screen(b).contains(pt):
                return tid, "move"
        return None, None

    def mousePressEvent(self, e):
        if not self.edit or self._pix is None or e.button() != Qt.MouseButton.LeftButton:
            return
        pt = e.position()
        tid, mode = self._hit(pt)
        if tid is None:
            x, y = self.to_video(pt)
            self._drag = {"mode": "new", "start": (x, y), "box": [x, y, x, y], "screen": pt}
        else:
            box = next(b for t, _x, b, _s in self.boxes if t == tid)
            self._drag = {"mode": mode, "tid": tid, "start": self.to_video(pt), "orig": list(box),
                          "box": list(box), "screen": pt}
            if tid != self.selected:
                self.selected = tid
                self.box_clicked.emit(tid)
        self.update()

    def mouseMoveEvent(self, e):
        d = self._drag
        if not d:
            self._update_cursor(e.position())
            return
        x, y = self.to_video(e.position())
        if d["mode"] == "new":
            sx, sy = d["start"]
            d["box"] = [min(sx, x), min(sy, y), max(sx, x), max(sy, y)]
        else:
            x1, y1, x2, y2 = d["orig"]
            dx, dy = x - d["start"][0], y - d["start"][1]
            m = 8 / self._k()  # 너무 작아지지 않게
            if d["mode"] == "move":
                x1, y1, x2, y2 = x1 + dx, y1 + dy, x2 + dx, y2 + dy
            else:
                if "l" in d["mode"]:
                    x1 = min(x1 + dx, x2 - m)
                if "r" in d["mode"]:
                    x2 = max(x2 + dx, x1 + m)
                if "t" in d["mode"]:
                    y1 = min(y1 + dy, y2 - m)
                if "b" in d["mode"]:
                    y2 = max(y2 + dy, y1 + m)
            d["box"] = [x1, y1, x2, y2]
            self.boxes = [(t, txt, d["box"] if t == d["tid"] else b, s) for t, txt, b, s in self.boxes]
        self.update()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        if not d:
            return
        moved = (e.position() - d["screen"]).manhattanLength() > 4
        if d["mode"] == "new":
            if moved:
                self.box_drawn.emit(d["box"])
            else:
                self.selected = None
                self.box_clicked.emit(None)
        elif moved:
            self.box_changed.emit(d["tid"], d["box"])
        self.update()

    def _update_cursor(self, pt: QPointF):
        if not self.edit or self._pix is None:
            self.unsetCursor()
            return
        _tid, mode = self._hit(pt)
        cursors = {"move": Qt.CursorShape.SizeAllCursor, "tl": Qt.CursorShape.SizeFDiagCursor,
                   "br": Qt.CursorShape.SizeFDiagCursor, "tr": Qt.CursorShape.SizeBDiagCursor,
                   "bl": Qt.CursorShape.SizeBDiagCursor}
        self.setCursor(cursors.get(mode, Qt.CursorShape.CrossCursor))


class Timeline(QWidget):
    """컷 위치, 선택한 인물의 등장 구간, 구간 효과, 시작/끝 표시, 재생 위치. 클릭·드래그로 이동."""

    seek = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(78)
        self.setMouseTracking(False)
        self.n = 0
        self.pos = 0
        self.cuts: list[int] = []
        self.presence: list[tuple[int, int]] = []
        self.segments: list[dict] = []
        self.mark_in: int | None = None
        self.mark_out: int | None = None
        self.fps = 30.0
        self.review: list[int] = []  # 확인이 필요한 위치

    def set_data(self, n: int, fps: float, cuts: list[int]):
        self.n, self.fps, self.cuts = n, fps, cuts
        self.update()

    def set_person(self, presence: list[tuple[int, int]], segments: list[dict]):
        self.presence, self.segments = presence, segments
        self.update()

    def set_pos(self, f: int):
        self.pos = f
        self.update()

    def _x(self, f: float) -> float:
        return 8 + (self.width() - 16) * (f / max(1, self.n))

    def _frame_at(self, x: float) -> int:
        return int(round((x - 8) / max(1, self.width() - 16) * self.n))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#1b1e24"))
        if not self.n:
            return
        w = self.width()
        # 눈금 (초)
        p.setPen(QColor("#4a505c"))
        secs = self.n / self.fps
        step = next(s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800) if secs / s <= (w / 70))
        t = 0.0
        while t <= secs:
            x = self._x(t * self.fps)
            p.drawLine(QPointF(x, 0), QPointF(x, 6))
            p.drawText(QPointF(x + 3, 14), f"{int(t // 60)}:{int(t % 60):02d}")
            t += step
        # 구간 효과 (위쪽 줄)
        for seg in self.segments:
            r = QRectF(self._x(seg["start"]), 20, max(2, self._x(seg["end"]) - self._x(seg["start"])), 18)
            p.fillRect(r, QColor(EFFECT_COLORS.get(seg["effect"]["type"], "#888")))
            p.setPen(QColor("#111"))
            p.drawText(r.adjusted(3, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, effect_text(seg["effect"]))
        # 인물 등장 구간 (아래쪽 줄)
        for a, b in self.presence:
            p.fillRect(QRectF(self._x(a), 44, max(1.5, self._x(b) - self._x(a)), 12), QColor("#3ebd93"))
        # 확인 필요한 곳 (맨 아래 주황 삼각형)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f0b429"))
        for f in self.review:
            x = self._x(f)
            p.drawPolygon([QPointF(x, 60), QPointF(x - 4, 68), QPointF(x + 4, 68)])
        # 컷
        p.setPen(QPen(QColor("#8b929e"), 1, Qt.PenStyle.DashLine))
        for c in self.cuts:
            p.drawLine(QPointF(self._x(c), 18), QPointF(self._x(c), 60))
        # 시작/끝 표시
        if self.mark_in is not None or self.mark_out is not None:
            a = self.mark_in if self.mark_in is not None else self.pos
            b = self.mark_out if self.mark_out is not None else self.pos
            a, b = min(a, b), max(a, b)
            p.fillRect(QRectF(self._x(a), 18, self._x(b) - self._x(a), 44), QColor(255, 255, 255, 40))
            p.setPen(QPen(QColor("#f0b429"), 2))
            for m in (self.mark_in, self.mark_out):
                if m is not None:
                    p.drawLine(QPointF(self._x(m), 18), QPointF(self._x(m), 62))
        # 재생 위치
        x = self._x(self.pos)
        p.setPen(QPen(QColor("#e5534b"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))

    def mousePressEvent(self, e):
        self.seek.emit(max(0, min(self.n - 1, self._frame_at(e.position().x()))))

    def mouseMoveEvent(self, e):
        self.mousePressEvent(e)


class EffectPicker(QWidget):
    """효과 종류 + 세부 값. allow_inherit이면 '기본 효과 따름'(None) 선택 가능."""

    changed = Signal()

    def __init__(self, allow_inherit: bool = False):
        super().__init__()
        self.allow_inherit = allow_inherit
        self.kind = QComboBox()
        if allow_inherit:
            self.kind.addItem("기본 효과 따름", None)
        for label, k in EFFECT_CHOICES:
            self.kind.addItem(label, k)

        self.blocks = QSpinBox(minimum=2, maximum=40, value=8, suffix=" 블록")
        self.strength = QSpinBox(minimum=5, maximum=100, value=30, suffix=" 강도")
        self.color_btn = QPushButton("■ #000000")
        self.color = "#000000"
        self.sticker = QComboBox()
        for label, v in STICKERS:
            self.sticker.addItem(label, v)
        self.image_btn = QPushButton("이미지 선택…")
        self.image_path = ""

        self.stack = QStackedWidget()
        self._pages = {}
        for key, w in [("empty", QWidget()), ("mosaic", self.blocks), ("blur", self.strength),
                       ("solid", self.color_btn), ("sticker", self.sticker), ("image", self.image_btn)]:
            self._pages[key] = self.stack.addWidget(w)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.kind, 1)
        lay.addWidget(self.stack, 1)

        self.kind.currentIndexChanged.connect(self._on_kind)
        self.blocks.valueChanged.connect(self.changed)
        self.strength.valueChanged.connect(self.changed)
        self.sticker.currentIndexChanged.connect(self.changed)
        self.color_btn.clicked.connect(self._pick_color)
        self.image_btn.clicked.connect(self._pick_image)
        self._on_kind(silent=True)

    def _on_kind(self, *_args, silent: bool = False):
        k = self.kind.currentData()
        self.stack.setCurrentIndex(self._pages.get(k, self._pages["empty"]))
        if k == "image" and not self.image_path and not silent:
            self._pick_image()
            return
        if not silent:
            self.changed.emit()

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self.color), self, "색 선택")
        if c.isValid():
            self.color = c.name()
            self.color_btn.setText(f"■ {self.color}")
            self.changed.emit()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "스티커 이미지 선택", "", "이미지 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.image_path = path
            self.image_btn.setText(path.rsplit("/", 1)[-1])
            self.changed.emit()
        elif not self.image_path:
            self.kind.setCurrentIndex(max(0, self.kind.findData("mosaic")))

    def effect(self) -> dict | None:
        k = self.kind.currentData()
        if k is None:
            return None
        value = {"mosaic": float(self.blocks.value()), "blur": float(self.strength.value()), "solid": self.color,
                 "sticker": self.sticker.currentData(), "image": self.image_path, "none": None}[k]
        return {"type": k, "value": value}

    def set_effect(self, e: dict | None):
        self.blockSignals(True)
        for w in (self.kind, self.blocks, self.strength, self.sticker):
            w.blockSignals(True)
        if e is None:
            self.kind.setCurrentIndex(0 if self.allow_inherit else self.kind.findData("mosaic"))
        else:
            self.kind.setCurrentIndex(self.kind.findData(e["type"]))
            v = e.get("value")
            if e["type"] == "mosaic" and v:
                self.blocks.setValue(int(v))
            elif e["type"] == "blur" and v:
                self.strength.setValue(int(v))
            elif e["type"] == "solid" and v:
                self.color = v
                self.color_btn.setText(f"■ {v}")
            elif e["type"] == "sticker" and v:
                self.sticker.setCurrentIndex(max(0, self.sticker.findData(v)))
            elif e["type"] == "image" and v:
                self.image_path = v
                self.image_btn.setText(v.rsplit("/", 1)[-1])
        self.stack.setCurrentIndex(self._pages.get(self.kind.currentData(), self._pages["empty"]))
        for w in (self.kind, self.blocks, self.strength, self.sticker):
            w.blockSignals(False)
        self.blockSignals(False)


def label(text: str, muted: bool = False) -> QLabel:
    lab = QLabel(text)
    if muted:
        lab.setStyleSheet("color: #8b929e;")
    return lab
