"""화면 부품: 영상 표시(상자 편집), 인물별 타임라인, 효과 선택."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollBar, QSizePolicy, QSlider,
                               QToolButton, QVBoxLayout, QWidget)

from ..effects import builtin_sticker

# 애플 시스템 색 (다크 모드)
EFFECT_COLORS = {"blur": "#0a84ff", "mosaic": "#bf5af2", "solid": "#8e8e93", "sticker": "#ff9f0a",
                 "image": "#30d158", "none": "#ff453a"}
# 효과 버튼 (키, 이름). 스티커는 모양별로 따로 버튼
PRESETS = [("blur", "블러"), ("mosaic", "모자이크"), ("solid", "단색"), ("none", "안 가림"),
           ("smile", "스마일"), ("heart", "하트"), ("image", "내 이미지"), ("inherit", "모두와 같게")]
PRESET_NAMES = dict(PRESETS)
SHAPE_CHOICES = [("사각형", "rect"), ("둥근 사각형", "rounded"), ("타원", "ellipse")]
SHAPED = ("mosaic", "blur", "solid")  # 모양·가장자리를 고를 수 있는 효과
ALL = -1  # "모든 인물"(기본 효과) 줄


def preset_of(e: dict | None) -> str:
    if e is None:
        return "inherit"
    if e["type"] == "sticker":
        return e.get("value") if e.get("value") in ("smile", "heart") else "smile"
    return e["type"]


def effect_short(e: dict | None) -> str:
    return PRESET_NAMES[preset_of(e)]


def effect_text(e: dict | None) -> str:
    """효과 자세한 설명 (구간 목록 등)."""
    if e is None:
        return "기본 효과"
    label = effect_short(e)
    v = e.get("value")
    if e["type"] == "image" and v:
        label = f"{label}·{v.rsplit('/', 1)[-1]}"
    elif e["type"] in ("mosaic", "blur") and v:
        label = f"{label} {int(v)}"
    extra = []
    if e.get("shape", "rect") != "rect":
        extra.append(dict((b, a) for a, b in SHAPE_CHOICES)[e["shape"]])
    if e.get("feather"):
        extra.append("부드럽게")
    if e.get("scale", 100) != 100:
        extra.append(f"{int(e['scale'])}%")
    return "·".join([label, *extra])


def preset_effect(key: str, prev: dict | None = None) -> dict | None:
    """버튼(키)으로 고른 효과. prev가 있으면 모양·가장자리·크기 설정을 이어받는다."""
    if key == "inherit":
        return None
    if key == "none":
        return {"type": "none", "value": None}
    e = {"blur": {"type": "blur", "value": 30.0}, "mosaic": {"type": "mosaic", "value": 8.0},
         "solid": {"type": "solid", "value": "#000000"}, "smile": {"type": "sticker", "value": "smile"},
         "heart": {"type": "sticker", "value": "heart"}, "image": {"type": "image", "value": ""}}[key]
    if prev is not None and prev.get("type") == e["type"] and key in SHAPED:
        e["value"] = prev.get("value", e["value"])  # 같은 종류면 강도·색도 유지
    if key in SHAPED:
        opts = {k: prev[k] for k in ("shape", "feather") if k in prev} if prev and prev.get("type") in SHAPED \
            else {"shape": "ellipse", "feather": 20.0}
        e.update(opts)
    if prev and "scale" in prev:
        e["scale"] = prev["scale"]
    return e


@lru_cache(maxsize=8)
def arrow_icon(redo: bool = False, size: int = 18) -> QIcon:
    """실행 취소/다시 실행 아이콘 (굽은 화살표)."""
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if redo:
        p.translate(size, 0)
        p.scale(-1, 1)
    pen = QPen(QColor("#f2f2f7"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawArc(QRectF(4, 5, 11, 9), 90 * 16, -200 * 16)
    p.drawPolyline([QPointF(7.5, 2.5), QPointF(4.5, 5), QPointF(7.5, 7.5)])
    p.drawLine(QPointF(4.5, 5), QPointF(9.5, 5))
    p.end()
    return QIcon(pix)


@lru_cache(maxsize=64)
def preset_icon(key: str, size: int = 40) -> QIcon:
    """효과 버튼용 작은 그림."""
    pix = QPixmap(size * 2, size * 2)  # 레티나
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(4, 4, size - 8, size - 8)
    if key == "blur":
        g = QRadialGradient(r.center(), r.width() / 2)
        g.setColorAt(0, QColor("#0a84ff"))
        g.setColorAt(0.55, QColor(10, 132, 255, 150))
        g.setColorAt(1, QColor(10, 132, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(r)
    elif key == "mosaic":
        n, c = 4, r.width() / 4
        shades = ["#bf5af2", "#9a44c4", "#d68cf7", "#7d3aa0"]
        for i in range(n):
            for j in range(n):
                p.fillRect(QRectF(r.x() + i * c, r.y() + j * c, c, c), QColor(shades[(i * 3 + j * 5) % 4]))
    elif key == "solid":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#636366"))
        p.drawRoundedRect(r, 6, 6)
    elif key in ("smile", "heart"):
        st = builtin_sticker(key)
        img = QImage(st.data, st.shape[1], st.shape[0], st.strides[0], QImage.Format.Format_ARGB32).copy()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(r, img)
    elif key == "image":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#30d158"))
        p.drawRoundedRect(r, 6, 6)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(r.x() + r.width() * 0.7, r.y() + r.height() * 0.3), 3.5, 3.5)
        p.drawPolygon([QPointF(r.x() + 4, r.bottom() - 4), QPointF(r.x() + r.width() * 0.4, r.y() + r.height() * 0.4),
                       QPointF(r.right() - 4, r.bottom() - 4)])
    elif key == "none":
        p.setPen(QPen(QColor("#ff453a"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r.adjusted(3, 3, -3, -3))
        p.drawLine(r.adjusted(7, 7, -7, -7).topRight(), r.adjusted(7, 7, -7, -7).bottomLeft())
    else:  # inherit
        p.setPen(QPen(QColor("#8e8e93"), 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 8, 8)
    p.end()
    return QIcon(pix)


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
        self.busy: str | None = None  # 분석 중 안내 문구
        self.busy_progress: float | None = None  # 0~1, 모르면 None
        self._spin = 0
        self._spin_timer = QTimer(self, interval=16)
        self._spin_timer.timeout.connect(self._tick_spin)

    def set_busy(self, text: str | None, progress: float | None = None):
        """분석 중: 화면을 어둡게 하고 가운데 진행 원과 문구를 띄운다. text=None이면 끔."""
        self.busy, self.busy_progress = text, progress
        if text and not self._spin_timer.isActive():
            self._spin_timer.start()
        elif not text:
            self._spin_timer.stop()
        self.update()

    def _tick_spin(self):
        self._spin = (self._spin + 6) % 360
        self.update()

    def _paint_busy(self, p: QPainter):
        a = self._area() if self._pix is not None else QRectF(self.rect())
        p.fillRect(a, QColor(0, 0, 0, 150))
        c = a.center()
        r = QRectF(c.x() - 26, c.y() - 40, 52, 52)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 50), 5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        pen = QPen(QColor("#0a84ff"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        if self.busy_progress is None:
            p.drawArc(r, -self._spin * 16, 90 * 16)
        else:
            p.drawArc(r, 90 * 16, -int(360 * 16 * max(0.02, min(1.0, self.busy_progress))))
            font = p.font()
            font.setPointSizeF(11)
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(QColor("#ffffff"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{int(self.busy_progress * 100)}%")
        font = p.font()
        font.setPointSizeF(14)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(a.x(), c.y() + 22, a.width(), 26), Qt.AlignmentFlag.AlignCenter, self.busy)

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
        p.fillRect(self.rect(), QColor("#0b0b0c"))
        if self._pix is None:
            if self.busy:
                self._paint_busy(p)
                return
            p.setPen(QColor("#8e8e93"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self._area(), self._pix, QRectF(self._pix.rect()))
        if self.busy:
            self._paint_busy(p)
            return
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


@dataclass
class Row:
    """타임라인 한 줄 (인물 한 명, 또는 맨 위 '모든 인물')."""
    pid: int
    name: str
    effect: dict  # 실제로 적용되는 효과 (기본 효과 반영)
    inherited: bool = False  # 기본 효과를 따르는 중
    presence: list[tuple[int, int]] = field(default_factory=list)  # 등장 구간 [시작, 끝)
    segments: list[dict] = field(default_factory=list)
    review: list[int] = field(default_factory=list)  # 확인이 필요한 위치
    warn: bool = False
    pix: QPixmap | None = None
    splits: list[int] = field(default_factory=list)  # 자른 곳


class PersonTimeline(QWidget):
    """파이널컷처럼 인물마다 한 줄. 막대 색 = 걸린 효과.

    - 눈금 클릭·끌기: 이동. 핀치·⌘+스크롤: 확대/축소, 가로 스크롤: 좌우 이동
    - 이름 클릭: 인물 선택(⌘-클릭 여러 명), 더블클릭: 이름 바꾸기, 효과 칩: 효과 메뉴, 우클릭: 메뉴
    - 막대 클릭: 그 조각 선택 + 이동. 자른 곳(노란 선)·막대 끝을 좌우로 끌면 길이 조절
    """

    seek = Signal(int)
    person_clicked = Signal(int, bool)  # 인물, ⌘ 누름
    piece_clicked = Signal(int, int)  # 인물, 프레임
    effect_menu = Signal(int, QPoint)
    context_menu = Signal(int, QPoint)  # 이름 칸 우클릭
    piece_menu = Signal(int, int, QPoint)  # 막대 칸 우클릭: 인물, 프레임
    split_moved = Signal(int, int, int)  # 인물, 원래 위치, 새 위치
    blade_at = Signal(int, int)  # 자르기 도구로 클릭: 인물, 프레임
    trimmed = Signal(int, int, int)  # 인물, 막대 끝 원래 위치, 새 위치
    renamed = Signal(int, str)

    RULER, ROW, LABEL, HBAR = 28, 40, 230, 10
    HANDLE = 6  # 끌기 손잡이 판정 거리(px)

    def __init__(self):
        super().__init__()
        self.n = 0
        self.fps = 30.0
        self.pos = 0
        self.cuts: list[int] = []
        self.rows: list[Row] = []
        self.current: int | None = None
        self.picked: set[int] = set()
        self.piece: tuple[int, int] | None = None  # 선택한 조각 (현재 인물)
        self.mark_in: int | None = None
        self.mark_out: int | None = None
        self.zoom = 1.0  # 1 = 영상 전체가 한 화면
        self.offset = 0.0  # 화면 왼쪽 끝 프레임
        self._drag: dict | None = None
        self.tool = "select"  # select | blade (파이널컷 A / B)
        self._hover: tuple[int, int] | None = None  # 자르기 도구에서 마우스가 가리키는 (줄, 프레임)
        self.scroll = QScrollBar(Qt.Orientation.Vertical, self)
        self.scroll.valueChanged.connect(self.update)
        self.hscroll = QScrollBar(Qt.Orientation.Horizontal, self)
        self.hscroll.valueChanged.connect(self._on_hscroll)
        self.editor = QLineEdit(self)
        self.editor.hide()
        self.editor.editingFinished.connect(self._finish_rename)
        self._edit_pid: int | None = None
        self.setMinimumHeight(self.RULER + self.ROW * 3 + self.HBAR)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)

    # 데이터
    def set_data(self, n: int, fps: float, cuts: list[int]):
        self.n, self.fps, self.cuts = n, fps, cuts
        self.zoom, self.offset = 1.0, 0.0
        self._layout()

    def set_rows(self, rows: list[Row], current: int | None, picked: set[int], piece=None):
        self.rows = rows
        self.set_selection(current, picked, piece)
        self._layout()

    def set_selection(self, current: int | None, picked: set[int], piece=None):
        self.current, self.picked, self.piece = current, set(picked), piece
        self.update()

    def set_tool(self, tool: str):
        self.tool = tool
        self._hover = None
        self.update()

    def set_pos(self, f: int):
        if f == self.pos:
            return
        self.pos = f
        vis = self._visible()
        if self.zoom > 1 and not (self.offset <= f < self.offset + vis):  # 재생 위치가 화면 밖이면 따라감
            self._set_offset(f - vis * 0.1)
        self.update()

    # 확대/축소
    def _visible(self) -> float:
        return max(1.0, self.n / self.zoom)

    def _set_offset(self, off: float):
        self.offset = max(0.0, min(self.n - self._visible(), off))
        self.hscroll.blockSignals(True)
        self.hscroll.setValue(int(self.offset))
        self.hscroll.blockSignals(False)
        self.update()

    def _on_hscroll(self, v: int):
        self.offset = float(v)
        self.update()

    def zoom_by(self, factor: float, anchor_x: float | None = None):
        if not self.n:
            return
        x0, x1 = self._span()
        ax = anchor_x if anchor_x is not None else self._x(self.pos)
        ax = min(max(ax, x0), x1)
        f_anchor = self.offset + (ax - x0) / (x1 - x0) * self._visible()
        max_zoom = max(1.0, self.n / max(10.0, self.fps * 1.0))  # 최대 1초가 한 화면
        self.zoom = min(max_zoom, max(1.0, self.zoom * factor))
        self._layout()
        self._set_offset(f_anchor - (ax - x0) / (x1 - x0) * self._visible())

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Type.NativeGesture and e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom_by(1 + e.value(), e.position().x())  # 트랙패드 핀치
            return True
        return super().event(e)

    def wheelEvent(self, e):
        mods = e.modifiers()
        dy = e.angleDelta().y()
        dx = e.pixelDelta().x() or e.angleDelta().x()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.AltModifier) \
                or e.position().y() < self.RULER:
            self.zoom_by(1.0015 ** dy, e.position().x())  # ⌘+스크롤, 눈금 위 스크롤: 확대/축소
            return
        if mods & Qt.KeyboardModifier.ShiftModifier and not dx:
            dx = dy
            dy = 0
        if dx and self.zoom > 1:
            x0, x1 = self._span()
            self._set_offset(self.offset - dx / (x1 - x0) * self._visible())
        if dy and self.scroll.isVisible():
            self.scroll.setValue(self.scroll.value() - dy // 2)

    # 배치·좌표
    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _layout(self):
        hb = self.HBAR if self.zoom > 1 else 0
        view = self.height() - self.RULER - hb
        total = len(self.rows) * self.ROW
        self.scroll.setGeometry(self.width() - 10, self.RULER, 10, max(0, view))
        self.scroll.setRange(0, max(0, total - view))
        self.scroll.setPageStep(max(1, view))
        self.scroll.setSingleStep(self.ROW // 2)
        self.scroll.setVisible(total > view)
        x0, x1 = self._span()
        self.hscroll.setGeometry(int(x0), self.height() - self.HBAR, int(x1 - x0), self.HBAR)
        self.hscroll.setVisible(self.zoom > 1)
        self.hscroll.blockSignals(True)
        self.hscroll.setRange(0, max(0, int(self.n - self._visible())))
        self.hscroll.setPageStep(int(self._visible()))
        self.hscroll.setValue(int(self.offset))
        self.hscroll.blockSignals(False)
        self.update()

    def _span(self) -> tuple[float, float]:
        x0 = self.LABEL + 10
        return x0, max(x0 + 1, self.width() - (18 if self.scroll.isVisible() else 12))

    def _x(self, f: float) -> float:
        x0, x1 = self._span()
        return x0 + (x1 - x0) * (f - self.offset) / self._visible()

    def _frame_at(self, x: float) -> int:
        x0, x1 = self._span()
        return max(0, min(self.n - 1, int(round(self.offset + (x - x0) / (x1 - x0) * self._visible()))))

    def _top(self, i: int) -> float:
        return self.RULER + i * self.ROW - self.scroll.value()

    def _row_at(self, y: float) -> int | None:
        if y < self.RULER or y > self.height() - (self.HBAR if self.zoom > 1 else 0):
            return None
        i = int((y - self.RULER + self.scroll.value()) // self.ROW)
        return i if 0 <= i < len(self.rows) else None

    def _chip(self, i: int) -> QRectF:
        return QRectF(self.LABEL - 84, self._top(i) + 10, 74, 20)

    def _name_rect(self, i: int) -> QRectF:
        return QRectF(46, self._top(i) + 7, self.LABEL - 84 - 52, self.ROW - 14)

    def _handle_at(self, i: int, x: float) -> dict | None:
        """막대 칸에서 끌 수 있는 곳: 자른 곳, 막대 끝."""
        r = self.rows[i]
        if r.pid == ALL:
            return None
        best = None
        for s in r.splits:
            d = abs(self._x(s) - x)
            if d <= self.HANDLE and (best is None or d < best[0]):
                best = (d, {"mode": "split", "orig": s})
        if best:
            return best[1]
        for a, b in r.presence:
            for edge in (a, b):
                d = abs(self._x(edge) - x)
                if d <= self.HANDLE and (best is None or d < best[0]):
                    best = (d, {"mode": "trim", "orig": edge})
        return best[1] if best else None

    # 그리기
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        x0, x1 = self._span()
        p.fillRect(self.rect(), QColor("#1c1c1e"))
        p.fillRect(QRectF(0, 0, self.LABEL, h), QColor("#232325"))
        p.save()
        p.setClipRect(QRectF(0, self.RULER, w, h - self.RULER))
        for i, r in enumerate(self.rows):
            t = self._top(i)
            if t + self.ROW < self.RULER or t > h:
                continue
            if r.pid == self.current or r.pid in self.picked:
                p.fillRect(QRectF(0, t, w, self.ROW), QColor(10, 132, 255, 50 if r.pid == self.current else 28))
            p.setPen(QColor("#2c2c2e"))
            p.drawLine(QPointF(0, t + self.ROW - 0.5), QPointF(w, t + self.ROW - 0.5))
            self._paint_label(p, i, r, t)
        p.setClipRect(QRectF(x0 - 4, self.RULER, x1 - x0 + 8, h - self.RULER))
        for i, r in enumerate(self.rows):
            t = self._top(i)
            if t + self.ROW < self.RULER or t > h:
                continue
            self._paint_clips(p, r, t)
        if self.n:
            p.setPen(QPen(QColor(255, 255, 255, 45), 1, Qt.PenStyle.DashLine))
            for c in self.cuts:
                x = self._x(c)
                p.drawLine(QPointF(x, self.RULER), QPointF(x, h))
        d = self._drag
        if self.tool == "blade" and self._hover and not d:  # 자르기 도구: 자를 자리 미리 보기
            i, f = self._hover
            t = self._top(i)
            x = self._x(f)
            p.setPen(QPen(QColor("#ff453a"), 1.5))
            p.drawLine(QPointF(x, t + 1), QPointF(x, t + self.ROW - 1))
        p.restore()
        self._paint_ruler(p)
        if self.n and x0 - 1 <= self._x(self.pos) <= x1 + 1:
            x = self._x(self.pos)
            p.setPen(QPen(QColor("#f2f2f7"), 1.5))
            p.drawLine(QPointF(x, self.RULER - 6), QPointF(x, h - (self.HBAR if self.zoom > 1 else 0)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f2f2f7"))
            p.drawPolygon([QPointF(x - 6, self.RULER - 12), QPointF(x + 6, self.RULER - 12), QPointF(x, self.RULER - 4)])

    def _paint_label(self, p: QPainter, i: int, r: Row, t: float):
        face = QRectF(12, t + 6, 28, 28)
        if r.pid == ALL:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a3a3c"))
            p.drawRoundedRect(face, 7, 7)
            p.setBrush(QColor("#aeaeb2"))
            for dx in (-5, 5):
                p.drawEllipse(QPointF(face.center().x() + dx, face.center().y() - 3), 3.5, 3.5)
                p.drawPie(QRectF(face.center().x() + dx - 6, face.center().y() + 2, 12, 12), 0, 180 * 16)
        elif r.pix is not None:
            p.save()
            path = QPainterPath()
            path.addRoundedRect(face, 7, 7)
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            p.drawPixmap(face.toRect(), r.pix)
            p.restore()
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a3a3c"))
            p.drawRoundedRect(face, 7, 7)
        font = p.font()
        font.setPointSizeF(12.5)
        font.setWeight(QFont.Weight.DemiBold if r.pid == self.current else QFont.Weight.Normal)
        p.setFont(font)
        name = r.name + ("  ⚠" if r.warn else "")
        area = self._name_rect(i)
        p.setPen(QColor("#ff9f0a") if r.warn else QColor("#f2f2f7"))
        p.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(area.width())))
        chip = self._chip(i)
        color = QColor(EFFECT_COLORS.get(r.effect["type"], "#8e8e93"))
        if r.inherited:  # 기본 효과를 따르는 중: 테두리만
            p.setPen(QPen(color, 1.2))
            fill = QColor(color)
            fill.setAlpha(40)
            p.setBrush(fill)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
        p.drawRoundedRect(chip, 10, 10)
        font.setPointSizeF(11)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, effect_short(r.effect) + " ▾")

    def _clip(self, p: QPainter, rect: QRectF, effect: dict, label: bool = True):
        color = QColor(EFFECT_COLORS.get(effect["type"], "#8e8e93"))
        fill = QColor(color)
        fill.setAlpha(210)
        p.setPen(QPen(color.lighter(135), 1))
        p.setBrush(QBrush(color, Qt.BrushStyle.BDiagPattern) if effect["type"] == "none" else fill)
        p.drawRoundedRect(rect, 4, 4)
        if label and rect.width() > 56:
            font = p.font()
            font.setPointSizeF(11)
            font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(QColor("#ffffff"))
            x0, _ = self._span()
            text_rect = QRectF(max(rect.x(), x0) + 7, rect.y(), rect.width() - 11, rect.height())
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, effect_short(effect))

    def _paint_clips(self, p: QPainter, r: Row, t: float):
        if not self.n:
            return
        x0, x1 = self._span()
        if r.pid == ALL:
            font = p.font()
            font.setPointSizeF(11)
            font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(QColor("#8e8e93"))
            p.drawText(QRectF(x0 + 4, t, x1 - x0, self.ROW), Qt.AlignmentFlag.AlignVCenter,
                       "효과를 따로 정하지 않은 모든 인물에 적용되는 기본 효과")
            return
        y, hh = t + 8, self.ROW - 16
        r = self._preview(r)
        bounds = [0, *r.splits, self.n]
        for a, b in r.presence:  # 막대를 자른 곳에서 나눠, 조각마다 그 조각의 효과 색으로
            cuts = [a, *[s for s in bounds if a < s < b], b]
            for s, e in zip(cuts, cuts[1:]):
                mid = (s + e) // 2
                eff = next((seg["effect"] for seg in reversed(r.segments) if seg["start"] <= mid < seg["end"]), r.effect)
                self._clip(p, QRectF(self._x(s) + (1 if s != a else 0), y,
                                     max(3.0, self._x(e) - self._x(s) - (1 if s != a else 0)), hh), eff)
        if r.pid == self.current and self.piece:  # 선택한 조각: 파이널컷처럼 노란 테두리
            a, b = self.piece
            p.setPen(QPen(QColor("#ffd60a"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self._x(a), t + 4, max(3.0, self._x(b) - self._x(a)), self.ROW - 8), 5, 5)
        p.setPen(QPen(QColor("#ffd60a"), 1.5))
        for s in r.splits:  # 자른 곳
            x = self._x(s)
            p.drawLine(QPointF(x, t + 3), QPointF(x, t + self.ROW - 3))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ff9f0a"))
        for f in r.review:
            x = self._x(f)
            p.drawPolygon([QPointF(x, t + self.ROW - 10), QPointF(x - 4.5, t + self.ROW - 2),
                           QPointF(x + 4.5, t + self.ROW - 2)])

    def _preview(self, r: Row) -> Row:
        """길이 조절 중이면 끄는 대로 막대 모양을 바꿔 보여준다."""
        d = self._drag
        if not d or "new" not in d or self.rows[d["row"]].pid != r.pid:
            return r
        old, new = d["orig"], d["new"]
        if d["mode"] == "split":
            sp = sorted(r.splits)
            i = sp.index(old) if old in sp else -1
            if i < 0:
                return r
            lo = (sp[i - 1] if i else 0) + 1
            hi = (sp[i + 1] if i + 1 < len(sp) else self.n) - 1
            new = max(lo, min(hi, new))
            segs = [{**s, "start": new if s["start"] == old else s["start"], "end": new if s["end"] == old else s["end"]}
                    for s in r.segments]
            return Row(**{**r.__dict__, "splits": [new if x == old else x for x in r.splits], "segments": segs})
        presence = []
        for a, b in r.presence:
            if a == old:
                a = min(new, b - 1)
            elif b == old:
                b = max(new, a + 1)
            presence.append((a, b))
        return Row(**{**r.__dict__, "presence": presence})

    def _paint_ruler(self, p: QPainter):
        w = self.width()
        p.fillRect(QRectF(0, 0, w, self.RULER), QColor("#2c2c2e"))
        p.setPen(QColor("#000000"))
        p.drawLine(QPointF(0, self.RULER - 0.5), QPointF(w, self.RULER - 0.5))
        font = p.font()
        font.setPointSizeF(10.5)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor("#8e8e93"))
        p.drawText(QRectF(14, 0, self.LABEL, self.RULER), Qt.AlignmentFlag.AlignVCenter, "인물")
        p.drawText(QRectF(self.LABEL - 84, 0, 74, self.RULER), Qt.AlignmentFlag.AlignCenter, "효과")
        if not self.n:
            return
        x0, x1 = self._span()
        p.save()
        p.setClipRect(QRectF(x0 - 2, 0, x1 - x0 + 40, self.RULER))
        vis_secs = self._visible() / self.fps
        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800)
                     if vis_secs / s <= (x1 - x0) / 80), 3600)
        t = (int(self.offset / self.fps / step)) * step
        end = (self.offset + self._visible()) / self.fps
        while t <= end + step:
            x = self._x(t * self.fps)
            p.setPen(QColor("#636366"))
            p.drawLine(QPointF(x, self.RULER - 7), QPointF(x, self.RULER - 1))
            p.setPen(QColor("#aeaeb2"))
            label = f"{int(t // 60)}:{t % 60:04.1f}" if step < 1 else f"{int(t // 60)}:{int(t % 60):02d}"
            p.drawText(QPointF(x + 4, 15), label)
            t += step
        if self.mark_in is not None and self.mark_out is not None:
            a, b = sorted((self.mark_in, self.mark_out))
            p.fillRect(QRectF(self._x(a), self.RULER - 5, max(2.0, self._x(b + 1) - self._x(a)), 4), QColor("#ffd60a"))
        p.restore()

    # 마우스
    def mousePressEvent(self, e):
        if not self.rows:
            return
        self._finish_rename()
        pos = e.position()
        if pos.y() < self.RULER:
            if pos.x() > self.LABEL:
                self._drag = {"mode": "seek"}
                self.seek.emit(self._frame_at(pos.x()))
            return
        i = self._row_at(pos.y())
        if i is None:
            return
        r = self.rows[i]
        gp = e.globalPosition().toPoint()
        in_label = pos.x() < self.LABEL
        if e.button() == Qt.MouseButton.RightButton:
            if r.pid not in self.picked:
                self.person_clicked.emit(r.pid, False)
            if in_label or r.pid == ALL:
                self.context_menu.emit(r.pid, gp)
            else:
                f = self._frame_at(pos.x())
                self.piece_clicked.emit(r.pid, f)
                self.piece_menu.emit(r.pid, f, gp)
            return
        if in_label:
            multi = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
            self.person_clicked.emit(r.pid, multi)
            chip = self._chip(i)
            if chip.contains(pos):
                self.effect_menu.emit(r.pid, self.mapToGlobal(chip.bottomLeft().toPoint()))
            return
        if self.tool == "blade" and r.pid != ALL:
            self.person_clicked.emit(r.pid, False)
            self.blade_at.emit(r.pid, self._frame_at(pos.x()))
            return
        handle = self._handle_at(i, pos.x())
        if handle:
            self._drag = {**handle, "row": i}
            self.person_clicked.emit(r.pid, False)
            return
        f = self._frame_at(pos.x())
        self.person_clicked.emit(r.pid, False)
        self.piece_clicked.emit(r.pid, f)
        self._drag = {"mode": "seek"}
        self.seek.emit(f)

    def mouseDoubleClickEvent(self, e):
        i = self._row_at(e.position().y())
        if i is not None and self.rows[i].pid != ALL and self._name_rect(i).contains(e.position()):
            self.start_rename(i)

    def start_rename(self, i: int):
        r = self.rows[i]
        self._edit_pid = r.pid
        self.editor.setGeometry(self._name_rect(i).toRect())
        self.editor.setText(r.name)
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _finish_rename(self):
        if self._edit_pid is None:
            return
        pid, self._edit_pid = self._edit_pid, None
        text = self.editor.text().strip()
        self.editor.hide()
        if text:
            self.renamed.emit(pid, text)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self._edit_pid is not None:
            self._edit_pid = None
            self.editor.hide()
            return
        super().keyPressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self._drag
        if not d and self.tool == "blade":
            i = self._row_at(pos.y())
            ok = i is not None and pos.x() > self.LABEL and self.rows[i].pid != ALL
            self._hover = (i, self._frame_at(pos.x())) if ok else None
            self.setCursor(Qt.CursorShape.CrossCursor if ok else Qt.CursorShape.ArrowCursor)
            self.setToolTip("클릭한 자리에서 자르기" if ok else "")
            self.update()
            return
        if not d:
            i = self._row_at(pos.y())
            handle = self._handle_at(i, pos.x()) if i is not None and pos.x() > self.LABEL else None
            self.setCursor(Qt.CursorShape.SizeHorCursor if handle else Qt.CursorShape.ArrowCursor)
            tip = ""
            if i is not None and self._chip(i).contains(pos):
                tip = "클릭해서 효과 바꾸기"
            elif handle:
                tip = "좌우로 끌어서 길이 조절"
            elif i is not None and pos.x() < self.LABEL and self.rows[i].pid != ALL:
                tip = "더블클릭해서 이름 바꾸기"
            self.setToolTip(tip)
            return
        f = self._frame_at(pos.x())
        if d["mode"] == "seek":
            self.seek.emit(f)
        else:
            d["new"] = f
            self.update()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        if not d or "new" not in d or d["new"] == d["orig"]:
            self.update()
            return
        pid = self.rows[d["row"]].pid
        if d["mode"] == "split":
            self.split_moved.emit(pid, d["orig"], d["new"])
        elif d["mode"] == "trim":
            self.trimmed.emit(pid, d["orig"], d["new"])
        self.update()


class SeekBar(QWidget):
    """재생 진행 바: 클릭·끌기로 바로 이동, 마우스를 올리면 두꺼워지고 그 위치 시각을 보여줌."""

    seek = Signal(int)

    def __init__(self):
        super().__init__()
        self.n = 1
        self.pos = 0
        self.time_text = lambda f: str(f)
        self._hover_x: float | None = None
        self.setFixedHeight(22)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_range(self, n: int):
        self.n = max(1, n)
        self.update()

    def set_pos(self, f: int):
        if f != self.pos:
            self.pos = f
            self.update()

    def _frame_at(self, x: float) -> int:
        return max(0, min(self.n - 1, int(round((x - 8) / max(1, self.width() - 16) * (self.n - 1)))))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self._hover_x is not None
        h = 6 if hover else 4
        track = QRectF(8, (self.height() - h) / 2, self.width() - 16, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(track, h / 2, h / 2)
        x = 8 + (self.width() - 16) * self.pos / max(1, self.n - 1)
        p.setBrush(QColor("#0a84ff"))
        p.drawRoundedRect(QRectF(track.x(), track.y(), max(h, x - 8), h), h / 2, h / 2)
        if hover:
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawEllipse(QPointF(self._hover_x, self.height() / 2), 3, 3)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(x, self.height() / 2), 7, 7)

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        f = self._frame_at(self._hover_x)
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(e.globalPosition().toPoint() + QPoint(0, -36), self.time_text(f), self)
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.seek.emit(f)
        self.update()

    def mousePressEvent(self, e):
        self.seek.emit(self._frame_at(e.position().x()))

    def leaveEvent(self, _):
        self._hover_x = None
        self.update()


class ValueSlider(QWidget):
    """슬라이더 + 값 표시."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, suffix: str = "", step: int = 1):
        super().__init__()
        self.slider = QSlider(Qt.Orientation.Horizontal, minimum=minimum, maximum=maximum, value=value,
                              singleStep=step, pageStep=step * 5)
        self.text = QLabel()
        self.text.setObjectName("muted")
        self.text.setMinimumWidth(42)
        self.text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.suffix = suffix
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.text)
        self.slider.valueChanged.connect(self._on)
        self._show(value)

    def _show(self, v: int):
        self.text.setText(f"{v}{self.suffix}")

    def _on(self, v: int):
        self._show(v)
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int):
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self._show(self.slider.value())


@lru_cache(maxsize=8)
def shape_icon(shape: str, size: int = 22) -> QIcon:
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#f2f2f7"), 1.6))
    r = QRectF(3, 5, size - 6, size - 10)
    if shape == "ellipse":
        p.drawEllipse(r)
    elif shape == "rounded":
        p.drawRoundedRect(r, 5, 5)
    else:
        p.drawRect(r)
    p.end()
    return QIcon(pix)


class EffectPicker(QWidget):
    """효과를 그림 버튼으로 고르고, 아래에서 슬라이더로 세부 조절. allow_inherit이면 '기본 따름'(None) 가능."""

    changed = Signal()

    def __init__(self, allow_inherit: bool = False):
        super().__init__()
        self.allow_inherit = allow_inherit
        self._key = "blur"
        self.image_path = ""
        self.color = "#000000"
        self._debounce = QTimer(self, singleShot=True, interval=120)  # 슬라이더를 끄는 동안 너무 자주 저장하지 않게
        self._debounce.timeout.connect(self.changed)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.btns: dict[str, QToolButton] = {}
        for i, (key, label_) in enumerate(PRESETS):
            b = QToolButton()
            b.setObjectName("preset")
            b.setCheckable(True)
            b.setText(label_)
            b.setIcon(preset_icon(key))
            b.setIconSize(QSize(30, 30))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumHeight(62)
            b.clicked.connect(lambda _=False, k=key: self._on_click(k))
            self.group.addButton(b)
            self.btns[key] = b
            grid.addWidget(b, i // 4, i % 4)

        # 내 이미지 보관함
        self.library = QWidget()
        self.lib_grid = QGridLayout(self.library)
        self.lib_grid.setContentsMargins(0, 0, 0, 0)
        self.lib_grid.setSpacing(6)
        self.lib_group = QButtonGroup(self)

        self.strength = ValueSlider(5, 100, 30)
        self.blocks = ValueSlider(2, 40, 8)
        self.color_btn = QPushButton("■ #000000")
        self.shape_btns: dict[str, QToolButton] = {}
        shapes = QWidget()
        sl = QHBoxLayout(shapes)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(4)
        self.shape_group = QButtonGroup(self)
        for label_, v in SHAPE_CHOICES:
            b = QToolButton()
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setIcon(shape_icon(v))
            b.setText(label_)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _=False: self.changed.emit())
            self.shape_group.addButton(b)
            self.shape_btns[v] = b
            sl.addWidget(b)
        self.shape_btns["rect"].setChecked(True)
        self.feather = ValueSlider(0, 50, 0, "%")
        self.feather.setToolTip("가장자리를 부드럽게 흐리는 정도. 얼굴은 항상 다 덮입니다")
        self.scale = ValueSlider(50, 300, 100, "%", step=5)
        self.scale.setToolTip("가리는 영역 크기 (100% = 이마·턱까지)")
        self.under = QCheckBox("투명한 틈으로 얼굴이 보이면 흐리기")
        self.form = QFormLayout()
        self.form.setContentsMargins(0, 10, 0, 0)
        self.form.setVerticalSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self._shapes = shapes
        for label_, w in (("강도", self.strength), ("블록 수", self.blocks), ("색", self.color_btn),
                          ("이미지", self.library), ("모양", shapes), ("가장자리", self.feather),
                          ("크기", self.scale), ("", self.under)):
            lab = QLabel(label_)
            lab.setObjectName("muted")
            self.form.addRow(lab, w)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(grid)
        lay.addLayout(self.form)

        for w in (self.strength, self.blocks, self.feather, self.scale):
            w.valueChanged.connect(lambda _v: self._debounce.start())
        self.under.toggled.connect(lambda _on: self.changed.emit())
        self.color_btn.clicked.connect(self._pick_color)
        self.set_inherit_allowed(allow_inherit)
        self._fill_library()
        self._sync()

    @property
    def key(self) -> str:
        return self._key

    def set_inherit_allowed(self, on: bool, label_: str = "모두와 같게"):
        self.allow_inherit = on
        self.btns["inherit"].setVisible(on)
        self.btns["inherit"].setText(label_)

    def _sync(self):
        k = self._key
        self.btns[k].setChecked(True)
        rows = {self.strength: k == "blur", self.blocks: k == "mosaic", self.color_btn: k == "solid",
                self.library: k == "image", self._shapes: k in SHAPED, self.feather: k in SHAPED,
                self.scale: k not in ("none", "inherit"), self.under: k in ("smile", "heart", "image")}
        for w, on in rows.items():
            self.form.setRowVisible(w, on)

    # 보관함
    def _fill_library(self):
        from .. import library
        while self.lib_grid.count():
            w = self.lib_grid.takeAt(0).widget()
            if w:
                self.lib_group.removeButton(w) if isinstance(w, QToolButton) else None
                w.deleteLater()
        items = library.images()
        for i, path in enumerate(items):
            b = QToolButton()
            b.setObjectName("thumb")
            b.setCheckable(True)
            b.setIcon(QIcon(QPixmap(str(path)).scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation)))
            b.setIconSize(QSize(40, 40))
            b.setFixedSize(52, 52)
            b.setToolTip(f"{path.name}\n우클릭: 보관함에서 지우기")
            b.setChecked(bool(self.image_path) and Path(self.image_path).name == path.name)
            b.clicked.connect(lambda _=False, pth=str(path): self._use_image(pth))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _pos, pth=str(path): self._remove_image(pth))
            self.lib_group.addButton(b)
            self.lib_grid.addWidget(b, i // 5, i % 5)
        add = QToolButton()
        add.setObjectName("thumb")
        add.setText("＋")
        add.setFixedSize(52, 52)
        add.setToolTip("이미지 올리기 (보관함에 저장되어 다음에도 바로 쓸 수 있어요)")
        add.clicked.connect(self._pick_image)
        n = len(items)
        self.lib_grid.addWidget(add, n // 5, n % 5)

    def _use_image(self, path: str):
        self.image_path = path
        self._key = "image"
        self._sync()
        self._fill_library()
        self.changed.emit()

    def _remove_image(self, path: str):
        from .. import library
        library.remove(path)
        self._fill_library()

    def _pick_image(self) -> bool:
        from .. import library
        path, _ = QFileDialog.getOpenFileName(self, "스티커 이미지 올리기", "", "이미지 (*.png *.jpg *.jpeg *.webp *.gif)")
        if not path:
            return False
        self._use_image(str(library.add(path)))
        return True

    def _on_click(self, key: str):
        if key == "image" and not self.image_path:
            from .. import library
            items = library.images()
            if items:  # 보관함에 있으면 가장 최근 것을 바로 씀
                self._use_image(str(items[0]))
            elif not self._pick_image():
                self._sync()  # 취소: 원래 버튼으로
            return
        self._key = key
        self._sync()
        self.changed.emit()

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self.color), self, "색 선택")
        if c.isValid():
            self.color = c.name()
            self.color_btn.setText(f"■ {self.color}")
            self.changed.emit()

    def effect(self) -> dict | None:
        k = self._key
        if k == "inherit":
            return None
        if k == "none":
            return {"type": "none", "value": None}
        e = {"blur": lambda: {"type": "blur", "value": float(self.strength.value())},
             "mosaic": lambda: {"type": "mosaic", "value": float(self.blocks.value())},
             "solid": lambda: {"type": "solid", "value": self.color},
             "smile": lambda: {"type": "sticker", "value": "smile"},
             "heart": lambda: {"type": "sticker", "value": "heart"},
             "image": lambda: {"type": "image", "value": self.image_path}}[k]()
        if k in SHAPED:
            shape = next(v for v, b in self.shape_btns.items() if b.isChecked())
            if shape != "rect":
                e["shape"] = shape
            if self.feather.value():
                e["feather"] = float(self.feather.value())
        if self.scale.value() != 100:
            e["scale"] = float(self.scale.value())
        if k in ("smile", "heart", "image") and self.under.isChecked() != (e["type"] == "sticker"):
            e["under"] = self.under.isChecked()
        return e

    def set_effect(self, e: dict | None):
        self._debounce.stop()
        self.under.blockSignals(True)
        self._key = preset_of(e) if (e is not None or self.allow_inherit) else "blur"
        e = e or {}
        v = e.get("value")
        if e.get("type") == "mosaic" and v:
            self.blocks.setValue(int(v))
        elif e.get("type") == "blur" and v:
            self.strength.setValue(int(v))
        elif e.get("type") == "solid" and v:
            self.color = v
            self.color_btn.setText(f"■ {v}")
        elif e.get("type") == "image" and v:
            self.image_path = v
        self.shape_btns[e.get("shape", "rect")].setChecked(True)
        self.feather.setValue(int(e.get("feather", 0)))
        self.scale.setValue(int(e.get("scale", 100)))
        self.under.setChecked(e.get("under", e.get("type") == "sticker"))
        if e.get("type") == "image":
            self._fill_library()
        self._sync()
        self.under.blockSignals(False)


def label(text: str, muted: bool = False) -> QLabel:
    lab = QLabel(text)
    if muted:
        lab.setObjectName("muted")
    return lab
