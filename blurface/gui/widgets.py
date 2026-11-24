"""화면 부품: 영상 표시(상자 편집), 인물별 타임라인, 효과 선택."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QComboBox, QFileDialog, QFormLayout, QGridLayout, QLabel,
                               QPushButton, QScrollBar, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..effects import builtin_sticker

# 애플 시스템 색 (다크 모드)
EFFECT_COLORS = {"blur": "#0a84ff", "mosaic": "#bf5af2", "solid": "#8e8e93", "sticker": "#ff9f0a",
                 "image": "#30d158", "none": "#ff453a"}
# 효과 버튼 (키, 이름). 스티커는 모양별로 따로 버튼
PRESETS = [("blur", "블러"), ("mosaic", "모자이크"), ("solid", "단색"), ("none", "안 가림"),
           ("smile", "스마일"), ("heart", "하트"), ("image", "내 이미지"), ("inherit", "기본 따름")]
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
            p.setPen(QColor("#8e8e93"))
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


class PersonTimeline(QWidget):
    """파이널컷처럼 인물마다 한 줄. 막대 색 = 걸린 효과.

    - 눈금 클릭·끌기: 이동
    - 줄 왼쪽(이름) 클릭: 인물 선택 (⌘-클릭 여러 명), 효과 칩 클릭: 효과 메뉴, 우클릭: 인물 메뉴
    - 줄 안쪽 클릭: 그 위치로 이동, 옆으로 끌기: 그 구간만 다른 효과
    """

    seek = Signal(int)
    person_clicked = Signal(int, bool)  # 인물, ⌘ 누름
    effect_menu = Signal(int, QPoint)
    range_picked = Signal(int, int, int, QPoint)  # 인물, 시작, 끝(포함 안 함), 메뉴 위치
    context_menu = Signal(int, QPoint)

    RULER, ROW, LABEL = 28, 40, 230

    def __init__(self):
        super().__init__()
        self.n = 0
        self.fps = 30.0
        self.pos = 0
        self.cuts: list[int] = []
        self.rows: list[Row] = []
        self.current: int | None = None
        self.picked: set[int] = set()
        self.mark_in: int | None = None
        self.mark_out: int | None = None
        self._drag: dict | None = None
        self.scroll = QScrollBar(Qt.Orientation.Vertical, self)
        self.scroll.valueChanged.connect(self.update)
        self.setMinimumHeight(self.RULER + self.ROW * 3)
        self.setMouseTracking(True)

    # 데이터
    def set_data(self, n: int, fps: float, cuts: list[int]):
        self.n, self.fps, self.cuts = n, fps, cuts
        self.update()

    def set_rows(self, rows: list[Row], current: int | None, picked: set[int]):
        self.rows = rows
        self.set_selection(current, picked)
        self._layout()

    def set_selection(self, current: int | None, picked: set[int]):
        self.current, self.picked = current, set(picked)
        self.update()

    def set_pos(self, f: int):
        if f != self.pos:
            self.pos = f
            self.update()

    # 배치·좌표
    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _layout(self):
        view = self.height() - self.RULER
        total = len(self.rows) * self.ROW
        self.scroll.setGeometry(self.width() - 10, self.RULER, 10, max(0, view))
        self.scroll.setRange(0, max(0, total - view))
        self.scroll.setPageStep(max(1, view))
        self.scroll.setSingleStep(self.ROW // 2)
        self.scroll.setVisible(total > view)
        self.update()

    def _span(self) -> tuple[float, float]:
        x0 = self.LABEL + 10
        return x0, max(x0 + 1, self.width() - (18 if self.scroll.isVisible() else 12))

    def _x(self, f: float) -> float:
        x0, x1 = self._span()
        return x0 + (x1 - x0) * f / max(1, self.n)

    def _frame_at(self, x: float) -> int:
        x0, x1 = self._span()
        return max(0, min(self.n - 1, int(round((x - x0) / (x1 - x0) * self.n))))

    def _top(self, i: int) -> float:
        return self.RULER + i * self.ROW - self.scroll.value()

    def _row_at(self, y: float) -> int | None:
        if y < self.RULER:
            return None
        i = int((y - self.RULER + self.scroll.value()) // self.ROW)
        return i if 0 <= i < len(self.rows) else None

    def _chip(self, i: int) -> QRectF:
        return QRectF(self.LABEL - 84, self._top(i) + 10, 74, 20)

    # 그리기
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
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
            self._paint_clips(p, r, t)
        if self.n:
            p.setPen(QPen(QColor(255, 255, 255, 45), 1, Qt.PenStyle.DashLine))
            for c in self.cuts:
                x = self._x(c)
                p.drawLine(QPointF(x, self.RULER), QPointF(x, h))
        d = self._drag
        if d and d.get("mode") == "range":
            t = self._top(d["row"])
            a, b = d["range"]
            p.setPen(QPen(QColor("#ffd60a"), 1.5))
            p.setBrush(QColor(255, 214, 10, 45))
            p.drawRoundedRect(QRectF(self._x(a), t + 3, max(2.0, self._x(b + 1) - self._x(a)), self.ROW - 6), 5, 5)
        p.restore()
        self._paint_ruler(p)
        if self.n:
            x = self._x(self.pos)
            p.setPen(QPen(QColor("#f2f2f7"), 1.5))
            p.drawLine(QPointF(x, self.RULER - 6), QPointF(x, h))
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
        area = QRectF(48, t, self.LABEL - 84 - 54, self.ROW)
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
            p.setFont(font)
            p.setPen(QColor("#ffffff"))
            p.drawText(rect.adjusted(7, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       effect_short(effect))

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
        for a, b in r.presence:
            self._clip(p, QRectF(self._x(a), y, max(3.0, self._x(b) - self._x(a)), hh), r.effect)
        for seg in r.segments:
            for a, b in r.presence:
                s, e = max(a, seg["start"]), min(b, seg["end"])
                if e > s:
                    self._clip(p, QRectF(self._x(s), y, max(3.0, self._x(e) - self._x(s)), hh), seg["effect"])
            color = QColor(EFFECT_COLORS.get(seg["effect"]["type"], "#8e8e93"))
            box = QRectF(self._x(seg["start"]), t + 3, max(3.0, self._x(seg["end"]) - self._x(seg["start"])), self.ROW - 6)
            p.setPen(QPen(color, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 5, 5)
            if not any(min(b, seg["end"]) > max(a, seg["start"]) for a, b in r.presence) and box.width() > 70:
                p.setPen(color)  # 이 구간에 등장하지 않으면 테두리만 보이므로 이름을 적어 둠
                p.drawText(box.adjusted(7, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter,
                           effect_short(seg["effect"]) + " (등장 안 함)")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffd60a"))
        for f in r.review:
            x = self._x(f)
            p.drawPolygon([QPointF(x, t + self.ROW - 10), QPointF(x - 4.5, t + self.ROW - 2),
                           QPointF(x + 4.5, t + self.ROW - 2)])

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
        secs = self.n / self.fps
        step = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800) if secs / s <= (x1 - x0) / 80), 3600)
        t = 0.0
        while t <= secs:
            x = self._x(t * self.fps)
            p.setPen(QColor("#636366"))
            p.drawLine(QPointF(x, self.RULER - 7), QPointF(x, self.RULER - 1))
            p.setPen(QColor("#aeaeb2"))
            p.drawText(QPointF(x + 4, 15), f"{int(t // 60)}:{int(t % 60):02d}")
            t += step
        if self.mark_in is not None and self.mark_out is not None:
            a, b = sorted((self.mark_in, self.mark_out))
            p.fillRect(QRectF(self._x(a), self.RULER - 5, max(2.0, self._x(b + 1) - self._x(a)), 4), QColor("#ffd60a"))

    # 마우스
    def mousePressEvent(self, e):
        if not self.n and not self.rows:
            return
        pos = e.position()
        if pos.y() < self.RULER:
            self._drag = {"mode": "seek"}
            self.seek.emit(self._frame_at(pos.x()))
            return
        i = self._row_at(pos.y())
        if i is None:
            return
        r = self.rows[i]
        gp = e.globalPosition().toPoint()
        if e.button() == Qt.MouseButton.RightButton:
            if r.pid not in self.picked:
                self.person_clicked.emit(r.pid, False)
            self.context_menu.emit(r.pid, gp)
            return
        if pos.x() < self.LABEL:
            multi = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
            self.person_clicked.emit(r.pid, multi)
            chip = self._chip(i)
            if chip.contains(pos):
                self.effect_menu.emit(r.pid, self.mapToGlobal(chip.bottomLeft().toPoint()))
            return
        self.person_clicked.emit(r.pid, False)
        self._drag = {"mode": "press", "row": i, "x0": pos.x(), "f0": self._frame_at(pos.x())}
        self.seek.emit(self._frame_at(pos.x()))

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self._drag
        if not d:
            i = self._row_at(pos.y())
            self.setToolTip("클릭해서 효과 바꾸기" if i is not None and self._chip(i).contains(pos) else
                            "옆으로 끌면 그 구간만 다른 효과" if i is not None and pos.x() > self.LABEL
                            and self.rows[i].pid != ALL else "")
            return
        f = self._frame_at(pos.x())
        if d["mode"] == "seek":
            self.seek.emit(f)
        elif d["mode"] in ("press", "range") and self.rows[d["row"]].pid != ALL:
            if d["mode"] == "press" and abs(pos.x() - d["x0"]) > 5:
                d["mode"] = "range"
            if d["mode"] == "range":
                d["range"] = (min(d["f0"], f), max(d["f0"], f))
                self.update()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        if d and d["mode"] == "range":
            a, b = d["range"]
            self.update()
            if b > a:
                self.range_picked.emit(self.rows[d["row"]].pid, a, b + 1, e.globalPosition().toPoint())

    def wheelEvent(self, e):
        if self.scroll.isVisible():
            self.scroll.setValue(self.scroll.value() - e.angleDelta().y() // 2)


class EffectPicker(QWidget):
    """효과를 그림 버튼으로 고르고, 아래에서 세부 조절. allow_inherit이면 '기본 따름'(None) 가능."""

    changed = Signal()

    def __init__(self, allow_inherit: bool = False):
        super().__init__()
        self.allow_inherit = allow_inherit
        self._key = "blur"
        self.image_path = ""
        self.color = "#000000"

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.btns: dict[str, QToolButton] = {}
        for i, (key, label) in enumerate(PRESETS):
            b = QToolButton()
            b.setObjectName("preset")
            b.setCheckable(True)
            b.setText(label)
            b.setIcon(preset_icon(key))
            b.setIconSize(QSize(30, 30))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumHeight(62)
            b.clicked.connect(lambda _=False, k=key: self._on_click(k))
            self.group.addButton(b)
            self.btns[key] = b
            grid.addWidget(b, i // 4, i % 4)

        self.strength = QSpinBox(minimum=5, maximum=100, value=30)
        self.blocks = QSpinBox(minimum=2, maximum=40, value=8)
        self.color_btn = QPushButton("■ #000000")
        self.image_btn = QPushButton("이미지 선택…")
        self.sticker = QComboBox()  # 예전 코드 호환용 (화면에는 안 보임)
        self.shape = QComboBox()
        for label, v in SHAPE_CHOICES:
            self.shape.addItem(label, v)
        self.feather = QSpinBox(minimum=0, maximum=50, value=0, suffix="%")
        self.feather.setToolTip("가장자리를 부드럽게 흐리는 정도. 얼굴은 항상 다 덮입니다")
        self.scale = QSpinBox(minimum=50, maximum=300, value=100, singleStep=10, suffix="%")
        self.scale.setToolTip("가리는 영역 크기 (100% = 이마·턱까지)")
        self.form = QFormLayout()
        self.form.setContentsMargins(0, 10, 0, 0)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        for label, w in (("강도", self.strength), ("블록 수", self.blocks), ("색", self.color_btn),
                         ("이미지", self.image_btn), ("모양", self.shape), ("가장자리", self.feather), ("크기", self.scale)):
            lab = QLabel(label)
            lab.setObjectName("muted")
            self.form.addRow(lab, w)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(grid)
        lay.addLayout(self.form)

        for w in (self.strength, self.blocks, self.feather, self.scale):
            w.valueChanged.connect(self.changed)
        self.shape.currentIndexChanged.connect(self.changed)
        self.color_btn.clicked.connect(self._pick_color)
        self.image_btn.clicked.connect(lambda: self._pick_image() and self.changed.emit())
        self.set_inherit_allowed(allow_inherit)
        self._sync()

    @property
    def key(self) -> str:
        return self._key

    def set_inherit_allowed(self, on: bool):
        self.allow_inherit = on
        self.btns["inherit"].setVisible(on)

    def _sync(self):
        k = self._key
        self.btns[k].setChecked(True)
        rows = {self.strength: k == "blur", self.blocks: k == "mosaic", self.color_btn: k == "solid",
                self.image_btn: k == "image", self.shape: k in SHAPED, self.feather: k in SHAPED,
                self.scale: k not in ("none", "inherit")}
        for w, on in rows.items():
            self.form.setRowVisible(w, on)

    def _on_click(self, key: str):
        if key == "image" and not self.image_path and not self._pick_image():
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

    def _pick_image(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(self, "스티커 이미지 선택", "", "이미지 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.image_path = path
            self.image_btn.setText(path.rsplit("/", 1)[-1])
            if self._key != "image":
                self._key = "image"
                self._sync()
        return bool(path)

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
            if self.shape.currentData() != "rect":
                e["shape"] = self.shape.currentData()
            if self.feather.value():
                e["feather"] = float(self.feather.value())
        if self.scale.value() != 100:
            e["scale"] = float(self.scale.value())
        return e

    def set_effect(self, e: dict | None):
        widgets = (self.strength, self.blocks, self.shape, self.feather, self.scale)
        for w in widgets:
            w.blockSignals(True)
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
            self.image_btn.setText(v.rsplit("/", 1)[-1])
        self.shape.setCurrentIndex(max(0, self.shape.findData(e.get("shape", "rect"))))
        self.feather.setValue(int(e.get("feather", 0)))
        self.scale.setValue(int(e.get("scale", 100)))
        self._sync()
        for w in widgets:
            w.blockSignals(False)


def label(text: str, muted: bool = False) -> QLabel:
    lab = QLabel(text)
    if muted:
        lab.setObjectName("muted")
    return lab
