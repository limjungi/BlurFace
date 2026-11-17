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


class VideoView(QWidget):
    """BGR 이미지를 비율 유지해 가운데 표시."""

    def __init__(self):
        super().__init__()
        self._pix: QPixmap | None = None
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.message = "영상을 열어 주세요 (⌘O 또는 끌어다 놓기)"

    def set_image(self, img: np.ndarray | None):
        if img is None:
            self._pix = None
        else:
            h, w = img.shape[:2]
            qimg = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888)
            self._pix = QPixmap.fromImage(qimg.copy())
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111317"))
        if self._pix is None:
            p.setPen(QColor("#8b929e"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        size = self._pix.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x, y = (self.width() - size.width()) // 2, (self.height() - size.height()) // 2
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(QRectF(x, y, size.width(), size.height()), self._pix, QRectF(self._pix.rect()))


class Timeline(QWidget):
    """컷 위치, 선택한 인물의 등장 구간, 구간 효과, 시작/끝 표시, 재생 위치. 클릭·드래그로 이동."""

    seek = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(74)
        self.setMouseTracking(False)
        self.n = 0
        self.pos = 0
        self.cuts: list[int] = []
        self.presence: list[tuple[int, int]] = []
        self.segments: list[dict] = []
        self.mark_in: int | None = None
        self.mark_out: int | None = None
        self.fps = 30.0

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
