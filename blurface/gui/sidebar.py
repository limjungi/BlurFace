"""왼쪽 사이드바: 프로젝트 보관함 목록 (표지, 이름, 길이·인물 수·수정 시각)."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from .. import projects

THUMB = QSize(64, 40)


def _ago(t: float) -> str:
    d = time.time() - t
    if d < 60:
        return "방금"
    if d < 3600:
        return f"{int(d // 60)}분 전"
    if d < 86400:
        return f"{int(d // 3600)}시간 전"
    if d < 86400 * 7:
        return f"{int(d // 86400)}일 전"
    return time.strftime("%Y. %-m. %-d.", time.localtime(t))


def _dur(secs: float) -> str:
    secs = int(round(secs))
    return f"{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}" if secs >= 3600 else f"{secs // 60}:{secs % 60:02d}"


def _cover(d: Path, missing: bool) -> QIcon:
    """표지를 둥근 모서리 썸네일로 (가운데를 잘라 채움). 원본 영상이 없으면 어둡게."""
    w, h = THUMB.width(), THUMB.height()
    pix = QPixmap(THUMB * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), 5, 5)
    p.setClipPath(clip)
    p.fillRect(QRectF(0, 0, w, h), QColor("#2c2c2e"))
    img = QPixmap(str(d / "cover.jpg"))
    if not img.isNull():
        img = img.scaled(THUMB * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
        img = img.copy((img.width() - w * 2) // 2, (img.height() - h * 2) // 2, w * 2, h * 2)
        p.drawPixmap(QRectF(0, 0, w, h), img, QRectF(img.rect()))
    if missing:
        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 150))
    p.end()
    return QIcon(pix)


class ProjectSidebar(QWidget):
    """프로젝트 목록. 클릭하면 열기, 우클릭 메뉴는 앱에서 처리."""

    open_requested = Signal(dict)  # 프로젝트 정보 (projects.list_projects 항목)
    menu_requested = Signal(dict, QPoint)
    add_requested = Signal()
    reveal_root = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setMinimumWidth(200)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.items: list[dict] = []
        title = QLabel("프로젝트")
        title.setObjectName("sideTitle")
        add = QToolButton()
        add.setText("＋")
        add.setToolTip("영상 열기 (⌘O)")
        add.setObjectName("play")
        add.setFixedSize(24, 24)
        add.clicked.connect(self.add_requested)
        head = QHBoxLayout()
        head.setContentsMargins(14, 12, 10, 6)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(add)
        self.list = QListWidget()
        self.list.setObjectName("projects")
        self.list.setIconSize(THUMB)
        self.list.setSpacing(2)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.itemClicked.connect(lambda it: self.open_requested.emit(self.items[self.list.row(it)]))
        self.list.customContextMenuRequested.connect(self._menu)
        self.empty = QLabel("아직 프로젝트가 없어요.\n영상을 열면 여기에 모입니다.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.where = QLabel()
        self.where.setObjectName("muted")
        self.where.setCursor(Qt.CursorShape.PointingHandCursor)
        self.where.setToolTip("Finder에서 보기 · 위치는 파일 메뉴 → 프로젝트 저장 위치에서 바꿀 수 있어요")
        self.where.mousePressEvent = lambda _e: self.reveal_root.emit()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(0)
        v.addLayout(head)
        v.addWidget(self.list, 1)
        v.addWidget(self.empty, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 6, 10, 0)
        foot.addWidget(self.where)
        v.addLayout(foot)

    def refresh(self, current: Path | None = None):
        self.items = projects.list_projects()
        self.list.clear()
        for m in self.items:
            d = m["dir"]
            if not (d / "cover.jpg").exists() and m["video_exists"]:
                projects.make_cover(d, m["video"])  # 예전 프로젝트는 표지가 없어서 처음 한 번 만듦
            missing = not m["video_exists"]
            sub = "⚠ 원본 영상 없음 (눌러서 다시 연결)" if missing else \
                f"{_dur(m.get('duration', 0))} · {m.get('persons', 0)}명 · {_ago(m.get('updated', 0))}"
            it = QListWidgetItem(_cover(d, missing), f"{m.get('name') or d.stem}\n{sub}")
            it.setSizeHint(QSize(0, THUMB.height() + 14))
            it.setToolTip(m.get("video", ""))
            if missing:
                it.setForeground(QColor("#8e8e93"))
            self.list.addItem(it)
            if current is not None and d == current:
                it.setSelected(True)
                self.list.setCurrentItem(it)
        has = bool(self.items)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        root = projects.root()
        home = str(Path.home())
        text = str(root).replace(home, "~", 1) if str(root).startswith(home) else str(root)
        self.where.setText(self.where.fontMetrics().elidedText(f"📁 {text}", Qt.TextElideMode.ElideMiddle,
                                                                 max(120, self.width() - 30)))

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is not None:
            self.menu_requested.emit(self.items[self.list.row(it)], self.list.mapToGlobal(pos))
