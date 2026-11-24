"""BlurFace 메인 화면.

파이널컷처럼: 위 왼쪽 미리보기, 위 오른쪽 설정(선택한 것에 따라 바뀜), 아래 인물별 타임라인.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QToolBar, QToolButton, QVBoxLayout, QWidget)

from ..effects import grow, shrink
from ..persons import face_crop
from ..project import Project
from ..render import compose
from ..video import probe
from .source import FrameSource
from .theme import apply_theme
from .widgets import (ALL, PRESETS, arrow_icon, EffectPicker, PersonTimeline, Row, SeekBar, VideoView, preset_effect,
                      preset_icon, preset_of)
from .workers import AnalyzeWorker, ExportWorker

VIDEO_EXT = "영상 (*.mp4 *.mov *.m4v *.mkv *.avi *.webm)"
UNDO_LIMIT = 200
HINT = "Space 재생 · A 선택 · B 자르기 도구 · ⌫ 부분 지우기 · 핀치로 확대 · F 전체 화면"


def fmt_time(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:05.2f}"


def section(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("section")
    return lab


def muted(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlurFace")
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.setUnifiedTitleAndToolBarOnMac(True)

        self.project: Project | None = None
        self.source: FrameSource | None = None
        self.frame = 0
        self.n_frames = 0
        self.fps = 30.0
        self.selected: int | None = None  # 선택한 인물 (ALL = 모든 인물)
        self.picked: set[int] = set()  # ⌘-클릭으로 여러 명 고른 인물
        self.sel_track: int | None = None  # 미리보기에서 선택한 상자(트랙)
        self.speed = 1.0
        self.piece: tuple[int, int] | None = None  # 선택한 조각 (자른 인물 줄의 한 부분)
        self._all_keep = False  # '모든 인물' 효과를 바꿀 때 따로 정한 사람은 그대로 두기로 했는지
        self.review: list[tuple[int, int, str]] = []
        self.worker = None
        self._threads: set = set()  # 스레드가 완전히 끝날 때까지 참조 유지 (먼저 지우면 앱이 죽음)
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._last_state: dict | None = None
        self._thumbs: dict[int, QPixmap] = {}
        self.play_timer = QTimer(self, interval=5)
        self.play_timer.timeout.connect(self._tick)
        self._play_start = (0.0, 0)

        self._build_toolbar()
        self._build_body()
        self._build_status()
        self._build_shortcuts()
        self._refresh_inspector()
        self._update_enabled()

    # ---------- 화면 구성 ----------
    def _build_toolbar(self):
        tb = QToolBar(movable=False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        self.act_open = QAction("열기", self, shortcut=QKeySequence.StandardKey.Open, triggered=self.open_dialog)
        self.act_export = QAction("내보내기", self, shortcut="Ctrl+E", triggered=self.export)
        self.act_undo = QAction(arrow_icon(), "실행 취소", self, shortcut=QKeySequence.StandardKey.Undo, triggered=self.undo)
        self.act_undo.setToolTip("실행 취소 (⌘Z)")
        self.act_redo = QAction(arrow_icon(True), "다시 실행", self, shortcut=QKeySequence.StandardKey.Redo, triggered=self.redo)
        self.act_redo.setToolTip("다시 실행 (⇧⌘Z)")
        self.act_boxes = QAction("얼굴 상자 고치기", self, checkable=True, shortcut="E", triggered=self._toggle_boxes)
        self.act_boxes.setToolTip("얼굴 상자를 보이게 하고 옮기기·크기 조절·새로 그리기 (E)")
        self.act_next = QAction("확인 필요한 곳 ▸", self, shortcut="N", triggered=self.next_review)
        self.act_blade = QAction("재생 위치에서 자르기", self, shortcut="Ctrl+B", triggered=self.blade)
        self.act_tool_select = QAction("선택", self, shortcut="A", checkable=True, checked=True,
                                       triggered=lambda: self.set_tool("select"))
        self.act_tool_blade = QAction("자르기", self, shortcut="B", checkable=True,
                                      triggered=lambda: self.set_tool("blade"))
        for a in (self.act_blade, self.act_tool_select, self.act_tool_blade):
            self.addAction(a)
        self.act_full = QAction("전체 화면", self, shortcut="F", triggered=self.toggle_fullscreen)
        self.act_zoom_in = QAction("확대", self, shortcut="Ctrl+=", triggered=lambda: self.timeline.zoom_by(1.5))
        self.act_zoom_out = QAction("축소", self, shortcut="Ctrl+-", triggered=lambda: self.timeline.zoom_by(1 / 1.5))
        for a in (self.act_full, self.act_zoom_in, self.act_zoom_out):
            self.addAction(a)
        self.act_next.setToolTip("자동 추적이 틀렸을 수 있는 다음 위치로 (N)")
        self.act_reanalyze = QAction("다시 분석", self, triggered=self.reanalyze)
        self.act_restore = QAction("분석 전으로 되돌리기", self, triggered=self.restore_dialog)
        self.act_restore.setToolTip("다시 분석하기 전 상태(고친 상자·효과 설정)로 되돌립니다")
        for a in (self.act_open, self.act_export):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_undo, self.act_redo):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.addSeparator()
        for a in (self.act_boxes, self.act_next):
            tb.addAction(a)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        for a in (self.act_reanalyze, self.act_restore):
            tb.addAction(a)

    def _build_body(self):
        # 미리보기
        self.view = VideoView()
        self.view.box_clicked.connect(self._on_box_clicked)
        self.view.box_changed.connect(self._on_box_changed)
        self.view.box_drawn.connect(self._on_box_drawn)
        self.play_btn = QToolButton()
        self.play_btn.setObjectName("play")
        self.play_btn.setText("▶")
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_label = QLabel("0:00.00")
        self.time_label.setObjectName("timecode")
        self.total_label = muted("/ 0:00.00")
        controls = QHBoxLayout()
        controls.setContentsMargins(12, 6, 12, 10)
        controls.addStretch()
        controls.addWidget(self.time_label)
        controls.addSpacing(14)
        controls.addWidget(self.play_btn)
        controls.addSpacing(14)
        controls.addWidget(self.total_label)
        controls.addStretch()
        self.speed_btns = {}
        for sp in (0.5, 1.0, 2.0):
            b = QToolButton()
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(sp == 1.0)
            b.setText(f"{sp:g}×")
            b.setToolTip(f"{sp:g}배속 재생")
            b.setFixedSize(42, 26)
            b.clicked.connect(lambda _=False, v=sp: self.set_speed(v))
            self.speed_btns[sp] = b
            controls.addWidget(b)
        controls.addSpacing(10)
        self.full_btn = QToolButton()
        self.full_btn.setText("⤢")
        self.full_btn.setToolTip("전체 화면 (F) · Esc로 나가기")
        self.full_btn.setObjectName("play")
        self.full_btn.setFixedSize(30, 30)
        self.full_btn.clicked.connect(self.toggle_fullscreen)
        controls.addWidget(self.full_btn)
        viewer = QWidget()
        viewer.setObjectName("viewer")
        vv = QVBoxLayout(viewer)
        vv.setContentsMargins(0, 0, 0, 0)
        vv.setSpacing(0)
        vv.addWidget(self.view, 1)
        self.seekbar = SeekBar()
        self.seekbar.seek.connect(self.seek)
        self.seekbar.time_text = lambda f: fmt_time(self._time(f))
        self.controls_w = QWidget()
        cv = QVBoxLayout(self.controls_w)
        cv.setContentsMargins(12, 4, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.seekbar)
        cv.addLayout(controls)
        vv.addWidget(self.controls_w)
        # 전체 화면에서는 마우스를 움직일 때만 재생 막대를 보여줌
        self._hide_timer = QTimer(self, singleShot=True, interval=2500, timeout=self._auto_hide_controls)
        self.view.installEventFilter(self)
        self.controls_w.installEventFilter(self)

        # 타임라인
        self.timeline = PersonTimeline()
        self.timeline.seek.connect(self.seek)
        self.timeline.person_clicked.connect(self.select_person)
        self.timeline.effect_menu.connect(self._effect_menu)
        self.timeline.context_menu.connect(self._context_menu)
        self.timeline.piece_clicked.connect(self._on_piece_clicked)
        self.timeline.piece_menu.connect(self._piece_menu)
        self.timeline.split_moved.connect(self._on_split_moved)
        self.timeline.trimmed.connect(self._on_trimmed)
        self.timeline.renamed.connect(self.rename)

        tl_bar = QHBoxLayout()
        tl_bar.setContentsMargins(10, 4, 10, 4)
        tl_bar.setSpacing(6)

        def tool_btn(action, tip, w=None):
            b = QToolButton()
            b.setObjectName("seg")
            b.setDefaultAction(action)
            b.setToolTip(tip)
            if w:
                b.setFixedWidth(w)
            b.setFixedHeight(26)
            tl_bar.addWidget(b)
            return b
        tool_btn(self.act_tool_select, "선택 도구 (A): 막대를 눌러 고르고, 끝을 끌어 길이 조절", 64)
        tool_btn(self.act_tool_blade, "자르기 도구 (B): 막대를 클릭한 자리에서 자르기", 64)
        tl_bar.addSpacing(10)
        hint = muted("자른 부분을 눌러 고른 뒤 효과를 바꾸거나 ⌫로 지우기")
        hint.setWordWrap(False)
        tl_bar.addWidget(hint)
        tl_bar.addStretch()
        self.act_zoom_fit = QAction("전체 보기", self, shortcut="Shift+Z", triggered=lambda: self.timeline.zoom_by(0.0001))
        self.addAction(self.act_zoom_fit)
        self.act_zoom_out.setText("−")
        self.act_zoom_in.setText("+")
        tool_btn(self.act_zoom_out, "타임라인 축소 (⌘−, 핀치)", 30)
        tool_btn(self.act_zoom_in, "타임라인 확대 (⌘+, 핀치)", 30)
        tool_btn(self.act_zoom_fit, "영상 전체가 보이게 (⇧Z)", 72)
        self.timeline_w = QWidget()
        tv = QVBoxLayout(self.timeline_w)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        tv.addLayout(tl_bar)
        tv.addWidget(self.timeline, 1)
        self.timeline.blade_at.connect(self._blade_at)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(viewer)
        self.inspector = self._build_inspector()
        top.addWidget(self.inspector)
        top.setSizes([1080, 360])
        top.setStretchFactor(0, 1)
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(self.timeline_w)
        main.setSizes([600, 260])
        main.setStretchFactor(0, 1)
        self.setCentralWidget(main)

    def _build_inspector(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(6)
        self.insp_title = QLabel("")
        self.insp_title.setObjectName("title")
        self.insp_sub = muted()
        self.name_edit = QLineEdit(placeholderText="이름")
        self.name_edit.editingFinished.connect(self._on_name)
        v.addWidget(self.insp_title)
        v.addWidget(self.insp_sub)
        v.addWidget(self.name_edit)

        v.addWidget(section("효과"))
        self.picker = EffectPicker(allow_inherit=True)
        self.picker.changed.connect(self._on_picker)
        v.addWidget(self.picker)

        # 조각(자른 구간)
        self.seg_section = QWidget()
        sv = QVBoxLayout(self.seg_section)
        sv.setContentsMargins(0, 0, 0, 0)
        self.piece_label = muted()
        sv.addWidget(self.piece_label)
        row = QHBoxLayout()
        self.piece_whole_btn = QPushButton("전체 시간에 적용")
        self.piece_whole_btn.setToolTip("부분 선택을 풀고, 이 사람이 나오는 전체 시간의 효과를 바꿉니다")
        self.piece_whole_btn.clicked.connect(lambda: self.select_piece(None))
        self.unsplit_btn = QPushButton("다시 하나로 합치기")
        self.unsplit_btn.setToolTip("자른 것을 모두 없애고 한 덩어리로 되돌립니다")
        self.unsplit_btn.clicked.connect(self._clear_splits)
        row.addWidget(self.piece_whole_btn)
        row.addWidget(self.unsplit_btn)
        sv.addLayout(row)
        v.insertWidget(v.indexOf(self.picker) - 1, self.seg_section)

        # 선택한 상자
        self.box_section = QWidget()
        bv = QVBoxLayout(self.box_section)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.addWidget(section("선택한 상자"))
        self.track_label = muted()
        bv.addWidget(self.track_label)
        self.btn_del_frame = QPushButton("이 프레임만 지우기")
        self.btn_del_frame.clicked.connect(lambda: self._track_edit("frame"))
        self.btn_del_track = QPushButton("전부 지우기 ⌫")
        self.btn_del_track.setObjectName("danger")
        self.btn_del_track.clicked.connect(lambda: self._track_edit("track"))
        self.btn_split = QPushButton("여기부터 다른 사람 (S)")
        self.btn_split.setToolTip("두 사람이 한 상자로 이어졌을 때: 현재 프레임부터 새 인물로 떼어냅니다")
        self.btn_split.clicked.connect(lambda: self._track_edit("split"))
        self.btn_reset = QPushButton("손댄 것 되돌리기")
        self.btn_reset.setToolTip("이 상자의 위치·크기 수정을 모두 지우고 자동 결과로 돌아갑니다")
        self.btn_reset.clicked.connect(lambda: self._track_edit("reset"))
        self.btn_del_range = QPushButton("구간 지우기")  # I/O로 정한 구간 (단축키 사용자용)
        self.btn_del_range.clicked.connect(lambda: self._track_edit("range"))
        self.btn_del_range.setVisible(False)
        self.assign_combo = QComboBox()
        self.assign_btn = QPushButton("인물 바꾸기")
        self.assign_btn.clicked.connect(lambda: self._track_edit("assign"))
        g = QGridLayout()
        g.setSpacing(6)
        g.addWidget(self.btn_del_frame, 0, 0)
        g.addWidget(self.btn_del_track, 0, 1)
        g.addWidget(self.btn_split, 1, 0)
        g.addWidget(self.btn_reset, 1, 1)
        g.addWidget(self.assign_combo, 2, 0)
        g.addWidget(self.assign_btn, 2, 1)
        bv.addLayout(g)
        v.addWidget(self.box_section)

        # 인물 동작
        self.person_actions = QWidget()
        av = QVBoxLayout(self.person_actions)
        av.setContentsMargins(0, 10, 0, 0)
        line = QFrame()
        line.setObjectName("line")
        av.addWidget(line)
        self.goto_btn = QPushButton("처음 등장한 곳으로")
        self.goto_btn.clicked.connect(self._goto_person)
        self.merge_btn = QPushButton("")
        self.merge_btn.clicked.connect(self.merge_selected)
        self.del_person_btn = QPushButton("인물 삭제 (얼굴 아님)")
        self.del_person_btn.setObjectName("danger")
        self.del_person_btn.clicked.connect(self.delete_selected_persons)
        for b in (self.goto_btn, self.merge_btn, self.del_person_btn):
            av.addWidget(b)
        v.addWidget(self.person_actions)
        v.addStretch()

        self.track_btns = [self.btn_del_frame, self.btn_del_range, self.btn_del_track, self.btn_split,
                           self.btn_reset, self.assign_combo, self.assign_btn]
        scroll = QScrollArea()
        scroll.setObjectName("panel")
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(330)
        return scroll

    def _build_status(self):
        self.status_label = QLabel("")
        self.progress = QProgressBar(maximumWidth=220, visible=False, textVisible=False)
        self.cancel_btn = QPushButton("취소", visible=False)
        self.cancel_btn.clicked.connect(lambda: self.worker and self.worker.cancel())
        sb = self.statusBar()
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(QLabel(HINT))
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.cancel_btn)

    def _build_shortcuts(self):
        for key, fn in [("Space", self.toggle_play), ("Left", lambda: self.step(-1)), ("Right", lambda: self.step(1)),
                        ("Shift+Left", lambda: self.step(-round(self.fps))),
                        ("Shift+Right", lambda: self.step(round(self.fps))),
                        ("I", self.mark_in), ("O", self.mark_out),
                        ("Backspace", self.delete_key), ("Delete", self.delete_key),
                        ("S", lambda: self._track_edit("split")), ("Escape", self._escape)]:
            QShortcut(QKeySequence(key), self, activated=fn)

    def _update_enabled(self):
        has_video = self.source is not None
        has_project = self.project is not None
        busy = self.worker is not None
        self.act_reanalyze.setEnabled(has_video and not busy)
        self.act_restore.setEnabled(has_video and not busy and bool(Project.backups(self.source.info.path)))
        self.act_export.setEnabled(has_project and not busy)
        self.act_undo.setEnabled(has_project and bool(self._undo))
        self.act_redo.setEnabled(has_project and bool(self._redo))
        self.act_next.setEnabled(has_project and bool(self.review))
        self.act_boxes.setEnabled(has_project)
        self.act_blade.setEnabled(has_project)
        has_track = has_project and self.sel_track is not None and self.sel_track in self.project.tracks
        for b in self.track_btns:
            b.setEnabled(has_track)

    # ---------- 열기 / 분석 ----------
    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "영상 열기", "", VIDEO_EXT)
        if path:
            self.open_video(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.open_video(urls[0].toLocalFile())

    def open_video(self, path: str):
        if self.worker:
            QMessageBox.information(self, "BlurFace", "작업이 끝난 뒤에 열 수 있습니다.")
            return
        self.pause()
        try:
            info = probe(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "열기 실패", f"영상을 열 수 없습니다.\n{e}")
            return
        if self.source:
            self.source.close()
        self.source = FrameSource(info)
        self.project = None
        self.selected = None
        self.picked = set()
        self.sel_track = None
        self.piece = None
        self.review = []
        self.n_frames, self.fps = max(1, info.n_frames), info.fps
        self.frame = 0
        self.timeline.mark_in = self.timeline.mark_out = None
        self.timeline.set_data(self.n_frames, self.fps, [])
        self.seekbar.set_range(self.n_frames)
        self.timeline.set_rows([], None, set())
        self.setWindowTitle(f"BlurFace — {Path(path).name}")
        project = Project.load(path)
        if project:
            self._set_project(project)
            self.status_label.setText(f"저장된 작업을 불러왔습니다 · 인물 {len(project.persons)}명")
        else:
            self._start_analysis(path)
            self._refresh_inspector()
        self.seek(0)
        self._update_enabled()

    def reanalyze(self):
        if not self.source:
            return
        if self.project and QMessageBox.question(
                self, "다시 분석",
                "얼굴을 처음부터 다시 찾습니다. 인물 번호가 바뀌고 고친 상자·효과 설정은 새로 시작합니다.\n\n"
                "지금 상태는 자동으로 백업되며, 언제든 '이전 상태로'로 돌아올 수 있습니다. 계속할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._start_analysis(self.source.info.path)

    def restore_dialog(self):
        if not self.source or self.worker:
            return
        backups = Project.backups(self.source.info.path)
        if not backups:
            QMessageBox.information(self, "되돌리기", "백업이 없습니다. 다시 분석할 때 자동으로 만들어집니다.")
            return
        labels = [Project.backup_summary(b) for b in backups]
        choice, ok = QInputDialog.getItem(self, "이전 상태로 되돌리기",
                                          "되돌릴 시점을 고르세요 (지금 상태도 백업해 둡니다):", labels, 0, False)
        if ok:
            self.restore_backup(backups[labels.index(choice)])

    def restore_backup(self, backup: Path):
        self.pause()
        project = Project.restore(self.source.info.path, backup)
        if project is None:
            QMessageBox.warning(self, "되돌리기", "백업을 읽을 수 없습니다.")
            return
        self.selected = None
        self._set_project(project)
        self.status_label.setText(f"되돌렸습니다 · {Project.backup_summary(backup)}")

    def _start_analysis(self, path: str):
        self.pause()
        w = AnalyzeWorker(path)
        w.done.connect(self._on_analyzed)
        self.view.set_busy("분석 준비 중…")
        w.progress.connect(lambda i, total: self.view.set_busy("얼굴 찾는 중", i / total if total else None))
        for sig in (w.done, w.failed, w.cancelled):
            sig.connect(lambda *_: self.view.set_busy(None))
        self._run_worker(w, "얼굴 찾는 중… (분석하는 동안에도 영상을 볼 수 있습니다)",
                         prep="분석 준비 중… (얼굴 인식 모델 불러오는 중, 몇 초 걸립니다)")

    def _on_analyzed(self, project: Project):
        self._set_project(project)
        self.status_label.setText(f"분석 완료 · 인물 {len(project.persons)}명 · 장면 전환 {len(project.cuts)}개 "
                                  f"({project.timings.get('total_analyze', 0):.0f}초)")

    def _set_project(self, project: Project):
        self.project = project
        self.sel_track = None
        self.piece = None
        self.picked = set()
        if self.selected not in project.persons:
            self.selected = ALL
        self._thumbs.clear()
        self._undo.clear()
        self._redo.clear()
        self._last_state = project.edit_state()
        self.n_frames, self.fps = project.n_frames, project.video.fps
        if self.source:
            self.source.set_pts(project.pts)
        self.timeline.set_data(self.n_frames, self.fps, project.cuts)
        self.seekbar.set_range(self.n_frames)
        self._update_review()
        self.frame = min(self.frame, self.n_frames - 1)
        self._refresh_all()

    # ---------- 작업 스레드 공통 ----------
    def _run_worker(self, w, text: str, prep: str | None = None):
        self.worker = w
        self._threads.add(w)
        w.finished.connect(lambda: self._threads.discard(w))
        start = time.perf_counter()

        def on_progress(i, total):
            if total:
                self.progress.setMaximum(total)
                self.progress.setValue(min(i, total))
            el = time.perf_counter() - start
            eta = f" · 남은 시간 약 {el / i * (total - i):.0f}초" if i and total else ""
            self.status_label.setText(f"{text}{eta}")

        def finish():
            self.worker = None
            self.progress.setVisible(False)
            self.cancel_btn.setVisible(False)
            self._update_enabled()

        w.progress.connect(on_progress)
        w.failed.connect(lambda msg: (finish(), QMessageBox.warning(self, "오류", msg)))
        w.cancelled.connect(lambda: (finish(), self.status_label.setText("취소했습니다")))
        w.done.connect(lambda *_: finish())
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.status_label.setText(prep or text)
        self._update_enabled()
        w.start()

    # ---------- 화면 갱신 ----------
    def _refresh_all(self):
        self._refresh_timeline()
        self._refresh_inspector()
        self.refresh_frame()
        self._update_enabled()

    def _thumb(self, pid: int) -> QPixmap | None:
        if pid not in self._thumbs:
            face = self.project.dir / "faces" / f"{pid}.jpg"
            self._thumbs[pid] = QPixmap(str(face)) if face.exists() else None
        return self._thumbs[pid]

    def _refresh_timeline(self):
        p = self.project
        if not p:
            return
        review: dict[int, list[int]] = {}
        for f, pid, _ in self.review:
            review.setdefault(pid, []).append(f)
        rows = [Row(ALL, "모든 인물", p.default_effect)]
        for pid, person in sorted(p.persons.items()):
            rows.append(Row(pid, person.name, p.effect_for(pid), person.effect is None,
                            self._runs(p.person_frames(pid)), person.segments, review.get(pid, []),
                            p.needs_review(pid), self._thumb(pid), list(person.splits)))
        self.timeline.set_rows(rows, self.selected, self.picked, self.piece)

    def _refresh_inspector(self):
        p, sel = self.project, self.selected
        is_person = p is not None and sel in p.persons
        for w in (self.name_edit, self.person_actions):
            w.setVisible(is_person)
        self.picker.setVisible(p is not None and sel is not None)
        self.insp_sub.setVisible(is_person or p is None)  # '모든 인물'은 설명 없이
        self.seg_section.setVisible(is_person and bool(p.persons[sel].splits))
        if p is None:
            self.insp_title.setText("BlurFace")
            self.insp_sub.setText("영상을 열거나 창에 끌어다 놓으면 얼굴을 자동으로 찾아 가려 줍니다.")
        elif not is_person:
            self.insp_title.setText("모든 인물")
            self.picker.set_inherit_allowed(False)
            self.picker.set_effect(p.default_effect)
        else:
            person = p.persons[sel]
            secs = len(p.person_frames(sel)) / p.video.fps
            self.insp_title.setText(person.name)
            warn = "\n⚠ 점수가 낮거나 아주 짧게 나와서 얼굴이 아닐 수 있어요." if p.needs_review(sel) else ""
            self.insp_sub.setText(f"#{sel + 1} · 등장 {secs:.1f}초{warn}")
            if not self.name_edit.hasFocus():
                self.name_edit.setText(person.name)
            if self.piece:
                a, b = self.piece
                seg = next((x for x in person.segments if x["start"] <= a and b <= x["end"]), None)
                self.piece_label.setText(f"선택한 부분 {fmt_time(p.time_of(a))} ~ {fmt_time(p.time_of(b))}만 바꾸는 중")
                self.picker.set_inherit_allowed(True, "나머지와 같게")
                self.picker.set_effect(seg["effect"] if seg else None)
            else:
                self.piece_label.setText(f"{len(p.pieces(sel))}부분으로 잘려 있어요 · 막대를 눌러 한 부분만 바꿀 수 있어요")
                self.picker.set_inherit_allowed(True)
                self.picker.set_effect(person.effect)
            self.piece_whole_btn.setVisible(self.piece is not None)
            n = len(self.picked)
            self.merge_btn.setText(f"선택한 {n}명을 한 사람으로 합치기")
            self.merge_btn.setVisible(n >= 2)
            self.del_person_btn.setText(f"선택한 {n}명 삭제 (얼굴 아님)" if n >= 2 else "인물 삭제 (얼굴 아님)")
        has_track = p is not None and self.sel_track in p.tracks
        self.box_section.setVisible(has_track)
        if has_track:
            self._fill_assign()

    @staticmethod
    def _runs(frames: list[int]) -> list[tuple[int, int]]:
        runs = []
        for f in frames:
            if runs and f <= runs[-1][1] + 1:
                runs[-1][1] = f
            else:
                runs.append([f, f])
        return [(a, b + 1) for a, b in runs]

    # ---------- 인물 선택 ----------
    def select_person(self, pid: int, multi: bool = False):
        if not self.project:
            return
        if multi and pid != ALL:
            if self.selected not in (None, ALL) and not self.picked:
                self.picked = {self.selected}
            self.picked ^= {pid}
            if not self.picked:
                self.picked = {pid}
        else:
            self.picked = {pid} if pid != ALL else set()
        if pid != self.selected:
            self.piece = None
            self._all_keep = False
        self.selected = pid
        if self.sel_track in self.project.tracks and self.project.tracks[self.sel_track].person != pid and pid != ALL:
            self.sel_track = None
        self.timeline.set_selection(self.selected, self.picked, self.piece)
        self._refresh_inspector()
        self.refresh_frame()
        self._update_enabled()

    # ---------- 효과 ----------
    def _import_asset(self, effect: dict | None) -> dict | None:
        """사용자 이미지를 프로젝트 폴더로 복사해 원본 파일을 옮기거나 지워도 계속 쓸 수 있게."""
        if not effect or effect["type"] != "image" or not effect.get("value"):
            return effect
        src = Path(effect["value"])
        assets = self.project.dir / "assets"
        if src.parent == assets:
            return effect
        assets.mkdir(parents=True, exist_ok=True)
        dst = assets / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
        return {**effect, "value": str(dst)}

    def _overridden(self) -> list[int]:
        """효과를 따로 정한 인물 (인물 효과나 구간 효과가 있음)."""
        return [pid for pid, person in self.project.persons.items() if person.effect is not None or person.segments]

    def set_effect(self, pid: int, effect: dict | None, ask: bool = True):
        effect = self._import_asset(effect)
        p = self.project
        if pid == ALL:
            if not effect:
                return
            over = self._overridden()
            if over and ask and not self._all_keep:
                choice = self._ask_all(len(over))
                if choice == "all":
                    for opid in over:
                        person = p.persons[opid]
                        person.effect, person.segments, person.splits = None, [], []
                elif choice == "keep":
                    self._all_keep = True  # 이번에 고르는 동안은 다시 묻지 않음
                else:
                    self._refresh_inspector()
                    return
            p.default_effect = effect
        elif self.piece and pid == self.selected:
            p.set_piece_effect(pid, *self.piece, effect)
        else:
            p.persons[pid].effect = effect
        self._changed()

    def _ask_all(self, n: int) -> str:
        """'all' | 'keep' | 'cancel'"""
        box = QMessageBox(self)
        box.setWindowTitle("모든 인물에 적용")
        box.setText(f"{n}명은 따로 정한 효과가 있어요.")
        box.setInformativeText("모두에게 적용하면 그 사람들의 개별 효과와 구간 효과가 사라집니다.")
        all_btn = box.addButton("모두에게 적용", QMessageBox.ButtonRole.DestructiveRole)
        keep_btn = box.addButton("따로 정한 사람은 그대로", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_btn)
        box.exec()
        return "all" if box.clickedButton() is all_btn else "keep" if box.clickedButton() is keep_btn else "cancel"

    def _on_picker(self):
        if self.project and self.selected is not None:
            self.set_effect(self.selected, self.picker.effect())

    def _ask_image(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "스티커 이미지 선택", "", "이미지 (*.png *.jpg *.jpeg *.webp *.gif)")
        return path

    def _preset(self, key: str, prev: dict | None) -> dict | None | bool:
        """메뉴에서 고른 효과. 이미지 선택을 취소하면 False."""
        e = preset_effect(key, prev)
        if key == "image":
            path = self._ask_image()
            if not path:
                return False
            e["value"] = path
        return e

    def _effect_menu(self, pid: int, pos):
        p = self.project
        cur = p.default_effect if pid == ALL else p.persons[pid].effect
        m = QMenu(self)
        for key, label_ in PRESETS:
            if key == "inherit" and pid == ALL:
                continue
            a = m.addAction(preset_icon(key), label_ if key != "inherit" else "'모든 인물'과 같게")
            a.setCheckable(True)
            a.setChecked(preset_of(cur) == key)
            a.triggered.connect(lambda _=False, k=key: self._apply_preset(pid, k))
        m.exec(pos)

    def _apply_preset(self, pid: int, key: str, piece: tuple[int, int] | None = None):
        p = self.project
        prev = p.default_effect if pid == ALL else p.effect_for(pid, piece[0] if piece else None)
        e = self._preset(key, prev)
        if e is False:
            return
        if pid != self.selected:
            self.select_person(pid)
        self.piece = piece
        self.set_effect(pid, e)

    # ---------- 자르기·부분 ----------
    def set_tool(self, tool: str):
        self.act_tool_select.setChecked(tool == "select")
        self.act_tool_blade.setChecked(tool == "blade")
        self.timeline.set_tool(tool)
        if tool == "blade":
            self.status_label.setText("자르기 도구: 인물 막대를 클릭한 자리에서 잘려요 · A로 선택 도구")

    def _blade_at(self, pid: int, frame: int):
        if pid not in self.project.persons:
            return
        if pid != self.selected:
            self.select_person(pid)
        self.seek(frame)
        self.blade()

    def delete_key(self):
        """⌫: 고른 부분이 있으면 그 시간 동안 이 사람을 가리지 않게 지우고, 아니면 고른 얼굴 상자를 지운다."""
        if self.view.edit and self.sel_track is not None:
            self._track_edit("track")
        elif self.piece and self.selected in (self.project.persons if self.project else {}):
            a, b = self.piece
            self._remove_person_range(self.selected, a, b)
            self.status_label.setText(f"{fmt_time(self._time(a))} ~ {fmt_time(self._time(b))} 부분을 지웠어요 (⌘Z 되돌리기)")
        elif self.sel_track is not None:
            self._track_edit("track")

    def blade(self):
        """선택한 인물 줄을 재생 위치에서 자른다 (파이널컷 ⌘B)."""
        p = self.project
        if not p:
            return
        if self.selected not in p.persons:
            self.status_label.setText("자를 인물 줄을 먼저 고르세요 (아래 타임라인에서 이름 클릭)")
            return
        if not p.split(self.selected, self.frame):
            return
        self.piece = p.piece_at(self.selected, self.frame)
        self.status_label.setText("잘랐어요 · 자른 부분을 눌러 효과를 바꾸거나 ⌫로 지울 수 있어요 (⌘Z 되돌리기)")
        self._changed()

    def select_piece(self, piece: tuple[int, int] | None):
        self.piece = piece
        self.timeline.set_selection(self.selected, self.picked, piece)
        self._refresh_inspector()

    def _on_piece_clicked(self, pid: int, frame: int):
        p = self.project
        if pid in p.persons and p.persons[pid].splits:
            self.select_piece(p.piece_at(pid, frame))
        else:
            self.select_piece(None)

    def _piece_menu(self, pid: int, frame: int, pos):
        if pid not in self.project.persons:
            return
        p = self.project
        piece = p.piece_at(pid, frame) if p.persons[pid].splits else None
        m = QMenu(self)
        sub = m.addMenu("이 부분 효과" if piece else "효과")
        for key, label_ in PRESETS:
            text = label_ if key != "inherit" else ("나머지와 같게" if piece else "'모든 인물'과 같게")
            sub.addAction(preset_icon(key), text).triggered.connect(
                lambda _=False, k=key: self._apply_preset(pid, k, piece))
        m.addAction("여기서 자르기").triggered.connect(lambda: self._blade_at(pid, frame))
        near = [x for x in p.persons[pid].splits if abs(self.timeline._x(x) - self.timeline._x(frame)) < 8]
        if near:
            m.addAction("여기 자른 것 합치기").triggered.connect(lambda: self._unsplit(pid, near[0]))
        if piece:
            m.addSeparator()
            m.addAction("이 부분 지우기 (가리지 않음)  ⌫").triggered.connect(lambda: self._remove_person_range(pid, *piece))
        m.exec(pos)

    def _unsplit(self, pid: int, frame: int):
        self.project.unsplit(pid, frame)
        self.piece = None
        self._changed()

    def _clear_splits(self):
        if self.selected in self.project.persons:
            for x in list(self.project.persons[self.selected].splits):
                self.project.unsplit(self.selected, x)
            self.piece = None
            self._changed()

    def _on_split_moved(self, pid: int, old: int, new: int):
        keep = self.piece
        new = self.project.move_split(pid, old, new)
        if keep:
            self.piece = self.project.piece_at(pid, keep[0] if keep[0] != old else new)
        self._changed()

    def _on_trimmed(self, pid: int, old: int, new: int):
        """막대 끝을 끌어 등장 길이 조절: 줄이면 그 구간 상자를 지우고, 늘리면 지웠던 상자를 되살린다."""
        p = self.project
        before = len(p.person_frames(pid))
        is_start = any(a == old for a, _ in self._runs(p.person_frames(pid)))
        a, b = sorted((old, new))
        grow_ = (is_start and new < old) or (not is_start and new > old)
        for tid in p.persons[pid].tracks:
            (p.restore_range if grow_ else p.remove_range)(tid, a, b)
        if grow_ and len(p.person_frames(pid)) == before:
            self.status_label.setText("더 늘릴 수 없어요. 그 시간에는 찾은 얼굴이 없습니다 (B 상자 편집으로 직접 그려 주세요)")
        self._changed(track_changed=True)

    def add_segment(self, pid: int, a: int, b: int, effect: dict):
        self.project.add_segment(pid, a, b, self._import_asset(effect))
        self.status_label.setText(f"{fmt_time(self.project.time_of(a))}~{fmt_time(self.project.time_of(b))} "
                                  f"구간 효과를 추가했습니다 (⌘Z로 되돌리기)")
        self._changed()

    def _remove_person_range(self, pid: int, a: int, b: int):
        for tid in list(self.project.persons[pid].tracks):
            self.project.remove_range(tid, a, b)
        self._changed(track_changed=True)

    def _context_menu(self, pid: int, pos):
        if pid == ALL or not self.project:
            return
        m = QMenu(self)
        m.addAction("효과 바꾸기…").triggered.connect(lambda: self._effect_menu(pid, pos))
        m.addAction("이름 바꾸기").triggered.connect(lambda: self._rename(pid))
        m.addAction("처음 등장한 곳으로").triggered.connect(self._goto_person)
        m.addSeparator()
        targets = sorted(self.picked) if pid in self.picked and len(self.picked) >= 2 else [pid]
        if len(targets) >= 2:
            m.addAction(f"선택한 {len(targets)}명을 한 사람으로 합치기").triggered.connect(self.merge_selected)
        else:
            m.addAction("다른 인물과 합치려면 ⌘-클릭으로 함께 고르세요").setEnabled(False)
        m.addAction(f"{'선택한 ' + str(len(targets)) + '명' if len(targets) > 1 else '인물'} 삭제 (얼굴 아님)") \
            .triggered.connect(self.delete_selected_persons)
        m.exec(pos)

    def _rename(self, pid: int):
        i = next((i for i, r in enumerate(self.timeline.rows) if r.pid == pid), None)
        if i is not None:
            self.timeline.start_rename(i)

    def rename(self, pid: int, name: str):
        if pid in self.project.persons and name and name != self.project.persons[pid].name:
            self.project.persons[pid].name = name
            self._changed()

    def _on_name(self):
        if self.project and self.selected in self.project.persons:
            name = self.name_edit.text().strip() or Project.default_name(self.selected)
            if name != self.project.persons[self.selected].name:
                self.project.persons[self.selected].name = name
                self._changed()

    def _goto_person(self):
        if self.project and self.selected in self.project.persons:
            frames = self.project.person_frames(self.selected)
            if frames:
                self.seek(frames[0])

    def mark_in(self):
        self.timeline.mark_in = self.frame
        self.timeline.update()

    def mark_out(self):
        self.timeline.mark_out = self.frame
        self.timeline.update()

    # ---------- 실행 취소 ----------
    def _changed(self, track_changed: bool = False):
        """모든 수정 뒤에 부른다: 실행 취소 기록 → 저장 → 화면 갱신."""
        if self._last_state is not None:
            self._undo.append(self._last_state)
            del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._last_state = self.project.edit_state()
        self._after_edit(track_changed)

    def _after_edit(self, track_changed: bool = True):
        p = self.project
        p.save()
        if track_changed:
            self._update_review()
        if self.selected not in p.persons:
            self.selected = ALL
        self.picked = {x for x in self.picked if x in p.persons}
        if self.sel_track is not None and self.sel_track not in p.tracks:
            self.sel_track = None
        if self.piece and (self.selected not in p.persons or self.piece not in p.pieces(self.selected)):
            self.piece = None
        self._refresh_all()

    def undo(self):
        self._step_history(self._undo, self._redo, "실행 취소")

    def redo(self):
        self._step_history(self._redo, self._undo, "다시 실행")

    def _step_history(self, src: list, dst: list, what: str):
        if not self.project or not src:
            return
        dst.append(self.project.edit_state())
        self.project.restore_state(src.pop())
        self._last_state = self.project.edit_state()
        self._thumbs.clear()
        self._after_edit()
        self.status_label.setText(what)

    # ---------- 상자 수정 ----------
    def _fill_assign(self):
        self.assign_combo.clear()
        p = self.project
        cur = p.tracks[self.sel_track].person if self.sel_track in p.tracks else None
        for pid, person in sorted(p.persons.items()):
            if pid != cur:
                self.assign_combo.addItem(f"→ {person.name}", pid)
        self.assign_combo.addItem("→ 새 인물", None)
        if self.sel_track in p.tracks:
            t = p.tracks[self.sel_track]
            kind = "직접 그림" if t.auto is None else "자동"
            edits = f" · 손댄 프레임 {len(t.keys)}" if t.keys else ""
            name = p.persons[t.person].name if t.person in p.persons else "-"
            self.track_label.setText(f"{name} · 상자 {self.sel_track} ({kind}){edits}")

    def _save_face(self, pid: int, box: list[float]):
        """새로 생긴 인물의 얼굴 사진 (현재 프레임에서)."""
        img = self.source.read(self.frame) if self.source else None
        if img is None:
            return
        k = self.source.scale
        faces = self.project.dir / "faces"
        faces.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(faces / f"{pid}.jpg"), face_crop(img, [x * k for x in box[:4]]))
        self._thumbs.pop(pid, None)

    def _on_box_clicked(self, tid):
        self.sel_track = tid
        if tid is not None and tid in self.project.tracks:
            self.select_person(self.project.tracks[tid].person)
            return
        self._refresh_inspector()
        self._update_enabled()
        self.refresh_frame()

    def _on_box_changed(self, tid: int, area: list):
        self.project.set_key(tid, self.frame, shrink(area))
        self._changed(track_changed=True)

    def _on_box_drawn(self, area: list):
        """빈 곳에 그린 상자: 이어 그리는 중인 상자가 있으면 거기에 키프레임 추가, 아니면 새 상자."""
        p, box = self.project, shrink(area)
        t = p.tracks.get(self.sel_track) if self.sel_track is not None else None
        if t is not None and t.auto is None and self.frame not in p.track_boxes(self.sel_track):
            p.set_key(self.sel_track, self.frame, box)
            self.status_label.setText("상자를 이어 그렸습니다 (사이 프레임은 자동으로 채움)")
        else:
            # 고른 인물이 이 프레임에 없으면 그 사람의 놓친 얼굴로, 아니면 새 인물
            pid = self.selected if self.selected in p.persons else None
            if pid is not None and any(p.tracks[tid].person == pid
                                       for tid, _b, _s in p.boxes_by_frame().get(self.frame, [])):
                pid = None
            self.sel_track = p.add_manual_track(self.frame, box, pid)
            new_pid = p.tracks[self.sel_track].person
            if new_pid != pid:
                self._save_face(new_pid, box)
            self.selected = new_pid
            self.picked = {new_pid}
            self.status_label.setText("상자를 추가했습니다 · 다른 프레임으로 가서 빈 곳을 끌면 이어 그립니다")
        self._changed(track_changed=True)

    def _track_edit(self, action: str):
        p, tid = self.project, self.sel_track
        if not p or tid is None or tid not in p.tracks:
            return
        if action == "frame":
            p.remove_range(tid, self.frame, self.frame + 1)
        elif action == "range":
            a, b = self.timeline.mark_in, self.timeline.mark_out
            if a is None or b is None:
                QMessageBox.information(self, "구간 지우기", "시작(I)과 끝(O) 위치를 먼저 정해 주세요.")
                return
            p.remove_range(tid, min(a, b), max(a, b) + 1)
        elif action == "track":
            p.remove_track(tid)
            self.sel_track = None
        elif action == "split":
            boxes = p.track_boxes(tid)
            if self.frame <= min(boxes, default=self.frame):
                self.status_label.setText("상자가 시작되는 프레임에서는 나눌 수 없습니다. 바뀌는 프레임으로 이동하세요.")
                return
            new = p.split_track(tid, self.frame)
            self._assign(new, None)
            self.sel_track = new
        elif action == "reset":
            p.clear_key(tid)
        elif action == "assign":
            self._assign(tid, self.assign_combo.currentData())
        self._changed(track_changed=True)

    def _assign(self, tid: int, pid: int | None):
        p = self.project
        new_pid = p.assign_track(tid, pid)
        if pid is None:
            boxes = p.track_boxes(tid)
            if self.frame in boxes:
                self._save_face(new_pid, boxes[self.frame][0])
        self.selected = new_pid
        self.picked = {new_pid}

    def merge_selected(self):
        pids = sorted(self.picked)
        if len(pids) < 2:
            return
        self.project.merge_persons(pids[0], pids[1:])
        self.selected = pids[0]
        self.picked = {pids[0]}
        self.status_label.setText(f"{len(pids)}명을 한 사람으로 합쳤습니다 (⌘Z로 되돌리기)")
        self._changed(track_changed=True)

    def delete_selected_persons(self):
        pids = sorted(self.picked) or ([self.selected] if self.selected in self.project.persons else [])
        if not pids:
            return
        for pid in pids:
            self.project.remove_person(pid)
        self.selected = ALL
        self.picked = set()
        self.status_label.setText(f"{len(pids)}명을 지웠습니다 (⌘Z로 되돌리기)")
        self._changed(track_changed=True)

    # ---------- 확인할 곳 ----------
    def _update_review(self):
        self.review = self.project.review_points() if self.project else []

    def next_review(self):
        if not self.review:
            return
        nxt = next((r for r in self.review if r[0] > self.frame), self.review[0])
        self.pause()
        if not self.act_boxes.isChecked():
            self.act_boxes.setChecked(True)
            self._toggle_boxes(True)
        if nxt[1] in self.project.persons:
            self.select_person(nxt[1])
        self.seek(nxt[0])
        self.status_label.setText(f"확인할 곳 {self.review.index(nxt) + 1}/{len(self.review)}: {nxt[2]}")

    # ---------- 재생 / 미리보기 ----------
    def _time(self, f: int) -> float:
        return self.project.time_of(f) if self.project else f / self.fps

    def seek(self, f: int):
        self.frame = max(0, min(self.n_frames - 1, f))
        self.refresh_frame()

    def step(self, d: int):
        self.pause()
        self.seek(self.frame + d)

    def refresh_frame(self):
        if not self.source:
            return
        img = self.source.read(self.frame)
        if img is None:
            return
        img = img.copy()
        if self.project:
            per = self.project.boxes_by_frame()
            compose(img, self.frame, self.project, per, scale=self.source.scale)
            self.view.video_size = (self.project.video.width, self.project.video.height)
            names = {pid: person.name for pid, person in self.project.persons.items()}
            self.view.set_boxes([(tid, names.get(self.project.tracks[tid].person, "?"), grow(b), src)
                                 for tid, b, src in per.get(self.frame, [])], self.sel_track)
        self.view.set_image(img)
        self.timeline.set_pos(self.frame)
        self.seekbar.set_pos(self.frame)
        self.time_label.setText(fmt_time(self._time(self.frame)))
        self.total_label.setText(f"/ {fmt_time(self._time(self.n_frames - 1))}")

    def toggle_play(self):
        if self.play_timer.isActive():
            self.pause()
        elif self.source:
            if self.frame >= self.n_frames - 1:
                self.frame = 0
            self._play_start = (time.perf_counter(), self.frame)
            self.play_timer.start()
            self.play_btn.setText("❚❚")

    def set_speed(self, speed: float):
        self.speed = speed
        for v, b in self.speed_btns.items():
            b.setChecked(v == speed)
        if self.play_timer.isActive():
            self._play_start = (time.perf_counter(), self.frame)

    def pause(self):
        self.play_timer.stop()
        self.play_btn.setText("▶")

    def _tick(self):
        t0, f0 = self._play_start
        target = f0 + int((time.perf_counter() - t0) * self.fps * self.speed)
        if target >= self.n_frames:
            self.pause()
            return
        if target != self.frame:
            self.frame = target
            self.refresh_frame()

    def _toggle_boxes(self, on: bool):
        self.view.edit = on
        self.view.unsetCursor()
        if on:
            self.status_label.setText("상자 편집: 상자를 끌어 옮기기 · 모서리로 크기 · 빈 곳을 끌어 새 상자")
        self.refresh_frame()

    def toggle_fullscreen(self):
        full = not self.isFullScreen()
        for w in (self.inspector, self.statusBar()):
            w.setVisible(not full)
        for tb in self.findChildren(QToolBar):
            tb.setVisible(not full)
        self.timeline_w.setVisible(not full)
        if full:
            self.showFullScreen()
            self._hide_timer.start()
        else:
            self.showNormal()
            self._hide_timer.stop()
            self.controls_w.setVisible(True)
            self.view.unsetCursor()
        self.full_btn.setText("⤡" if full else "⤢")

    def _auto_hide_controls(self):
        if self.isFullScreen() and not self.controls_w.underMouse():
            self.controls_w.setVisible(False)
            self.view.setCursor(Qt.CursorShape.BlankCursor)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.MouseMove and self.isFullScreen():
            if not self.controls_w.isVisible():
                self.controls_w.setVisible(True)
                self.view.unsetCursor()
            self._hide_timer.start()
        return super().eventFilter(obj, e)

    def _escape(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        elif self.piece:
            self.select_piece(None)

    # ---------- 내보내기 ----------
    def export(self):
        if not self.project or self.worker:
            return
        self.pause()
        from .export_dialog import ExportDialog
        dlg = ExportDialog(self.project, self)
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return
        out = dlg.out_path()
        if Path(out).exists() and QMessageBox.question(self, "내보내기", f"{Path(out).name} 파일이 이미 있어요. 덮어쓸까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        w = ExportWorker(self.project, out, dlg.options())
        w.done.connect(self._on_exported)
        self._run_worker(w, "내보내는 중…")

    def _on_exported(self, out: str, secs: float):
        self.status_label.setText(f"내보내기 완료 ({secs:.0f}초): {out}")
        box = QMessageBox(self)
        box.setWindowTitle("내보내기 완료")
        box.setText(f"{Path(out).name}\n({secs:.0f}초 걸림)")
        finder = box.addButton("Finder에서 보기", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is finder:
            subprocess.run(["open", "-R", out], check=False)

    def closeEvent(self, e):
        for t in list(self._threads):
            t.cancel()
            t.wait(10000)
        if self.source:
            self.source.close()
        super().closeEvent(e)


def main(argv: list[str] | None = None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("BlurFace")
    apply_theme(app)
    win = MainWindow()
    win.show()
    files = [a for a in argv[1:] if Path(a).exists()]
    if files:
        QTimer.singleShot(0, lambda: win.open_video(files[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
