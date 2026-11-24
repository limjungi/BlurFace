"""BlurFace 메인 화면."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QInputDialog,
                               QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QToolBar, QVBoxLayout, QWidget)

import cv2

from ..effects import grow, shrink
from ..persons import face_crop
from ..project import Project
from ..render import compose
from ..video import probe
from .source import FrameSource
from .widgets import EffectPicker, Timeline, VideoView, effect_text, label
from .workers import AnalyzeWorker, ExportWorker

ALL = -1  # 인물 목록의 "모든 인물 기본 효과" 항목
VIDEO_EXT = "영상 (*.mp4 *.mov *.m4v *.mkv *.avi *.webm)"
UNDO_LIMIT = 200


def fmt_time(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:05.2f}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlurFace")
        self.resize(1440, 880)
        self.setAcceptDrops(True)

        self.project: Project | None = None
        self.source: FrameSource | None = None
        self.frame = 0
        self.n_frames = 0
        self.fps = 30.0
        self.selected: int | None = None
        self.worker = None
        self._threads: set = set()  # 스레드가 완전히 끝날 때까지 참조 유지 (먼저 지우면 앱이 죽음)
        self.sel_track: int | None = None  # 미리보기에서 선택한 상자(트랙)
        self.review: list[tuple[int, str]] = []
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._last_state: dict | None = None
        self.play_timer = QTimer(self, interval=5)
        self.play_timer.timeout.connect(self._tick)
        self._play_start = (0.0, 0)

        self._build_toolbar()
        self._build_body()
        self._build_status()
        self._build_shortcuts()
        self._update_enabled()

    # ---------- 화면 구성 ----------
    def _build_toolbar(self):
        tb = QToolBar(movable=False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)
        self.act_open = QAction("열기", self, shortcut=QKeySequence.StandardKey.Open, triggered=self.open_dialog)
        self.act_reanalyze = QAction("다시 분석", self, triggered=self.reanalyze)
        self.act_restore = QAction("이전 상태로 되돌리기", self, triggered=self.restore_dialog)
        self.act_restore.setToolTip("다시 분석하기 전 상태(고친 상자·효과 설정)로 되돌립니다")
        self.act_export = QAction("내보내기", self, shortcut="Ctrl+E", triggered=self.export)
        self.act_undo = QAction("실행 취소", self, shortcut=QKeySequence.StandardKey.Undo, triggered=self.undo)
        self.act_redo = QAction("다시 실행", self, shortcut=QKeySequence.StandardKey.Redo, triggered=self.redo)
        self.act_boxes = QAction("상자 편집", self, checkable=True, shortcut="B", triggered=self._toggle_boxes)
        self.act_next = QAction("다음 확인 지점", self, shortcut="N", triggered=self.next_review)
        for a in (self.act_open, self.act_reanalyze, self.act_restore, self.act_export):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_undo, self.act_redo):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_boxes, self.act_next):
            tb.addAction(a)

    def _build_body(self):
        # 왼쪽: 인물 목록
        self.persons = QListWidget()
        self.persons.setIconSize(QSize(56, 56))
        self.persons.setSpacing(2)
        self.persons.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.persons.currentItemChanged.connect(self._on_person_selected)
        self.persons.itemSelectionChanged.connect(self._update_enabled)
        self.merge_btn = QPushButton("선택한 인물 합치기")
        self.merge_btn.setToolTip("⌘-클릭으로 여러 명을 고른 뒤 누르면 한 사람으로 합칩니다 (번호가 가장 작은 사람 설정을 따름)")
        self.merge_btn.clicked.connect(self.merge_selected)
        self.del_person_btn = QPushButton("인물 삭제 (얼굴 아님)")
        self.del_person_btn.clicked.connect(self.delete_selected_persons)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.addWidget(label("인물"))
        lv.addWidget(self.persons)
        lv.addWidget(self.merge_btn)
        lv.addWidget(self.del_person_btn)

        # 가운데: 영상 + 재생 + 타임라인
        self.view = VideoView()
        self.view.box_clicked.connect(self._on_box_clicked)
        self.view.box_changed.connect(self._on_box_changed)
        self.view.box_drawn.connect(self._on_box_drawn)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(44)
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_label = label("0:00.00 / 0:00.00", muted=True)
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek)
        controls = QHBoxLayout()
        controls.addWidget(self.play_btn)
        controls.addWidget(self.time_label)
        controls.addStretch()
        controls.addWidget(label("Space 재생 · ←/→ 1프레임 · ⇧←/→ 1초 · I/O 구간 시작/끝 · B 상자 편집 · N 확인 지점",
                                 muted=True))
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(4, 8, 4, 8)
        cv.addWidget(self.view, 1)
        cv.addLayout(controls)
        cv.addWidget(self.timeline)

        # 오른쪽: 선택한 인물 설정
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._on_name)
        self.base_picker = EffectPicker(allow_inherit=True)
        self.base_picker.changed.connect(self._on_base_effect)
        self.goto_btn = QPushButton("처음 등장한 곳으로")
        self.goto_btn.clicked.connect(self._goto_person)
        self.info_label = label("", muted=True)
        self.info_label.setWordWrap(True)
        base_box = QGroupBox("효과")
        bf = QFormLayout(base_box)
        bf.addRow("이름", self.name_edit)
        bf.addRow("효과", self.base_picker)
        bf.addRow(self.goto_btn)
        bf.addRow(self.info_label)

        self.in_label = label("—", muted=True)
        self.out_label = label("—", muted=True)
        in_btn = QPushButton("시작 = 현재 (I)")
        in_btn.clicked.connect(self.mark_in)
        out_btn = QPushButton("끝 = 현재 (O)")
        out_btn.clicked.connect(self.mark_out)
        self.seg_picker = EffectPicker()
        self.seg_picker.set_effect({"type": "sticker", "value": "heart"})
        self.seg_add = QPushButton("구간 추가")
        self.seg_add.clicked.connect(self._add_segment)
        self.seg_table = QTableWidget(0, 3)
        self.seg_table.setHorizontalHeaderLabels(["시작", "끝", "효과"])
        self.seg_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.seg_table.verticalHeader().setVisible(False)
        self.seg_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.seg_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.seg_table.cellDoubleClicked.connect(lambda r, _c: self._goto_segment(r))
        self.seg_del = QPushButton("선택 구간 삭제")
        self.seg_del.clicked.connect(self._delete_segment)
        seg_box = QGroupBox("구간 효과 (이 시간 동안만 다른 효과)")
        sv = QVBoxLayout(seg_box)
        row = QHBoxLayout()
        row.addWidget(in_btn)
        row.addWidget(self.in_label)
        sv.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(out_btn)
        row.addWidget(self.out_label)
        sv.addLayout(row)
        sv.addWidget(self.seg_picker)
        sv.addWidget(self.seg_add)
        sv.addWidget(self.seg_table, 1)
        sv.addWidget(self.seg_del)

        box_box = QGroupBox("상자 수정 (B로 켜기)")
        bv = QVBoxLayout(box_box)
        tip = label("빈 곳을 끌면 새 상자 · 상자를 끌면 이동 · 모서리로 크기 조절. "
                    "고친 프레임 사이는 자동으로 이어집니다.", muted=True)
        tip.setWordWrap(True)
        bv.addWidget(tip)
        self.track_label = label("선택한 상자 없음", muted=True)
        bv.addWidget(self.track_label)
        self.btn_del_frame = QPushButton("이 프레임만 지우기")
        self.btn_del_frame.clicked.connect(lambda: self._track_edit("frame"))
        self.btn_del_range = QPushButton("시작~끝 구간 지우기")
        self.btn_del_range.clicked.connect(lambda: self._track_edit("range"))
        self.btn_del_track = QPushButton("이 상자 전부 지우기 (⌫)")
        self.btn_del_track.clicked.connect(lambda: self._track_edit("track"))
        self.btn_split = QPushButton("여기부터 다른 사람 (S)")
        self.btn_split.setToolTip("두 사람이 한 상자로 이어졌을 때: 현재 프레임부터 새 인물로 떼어냅니다")
        self.btn_split.clicked.connect(lambda: self._track_edit("split"))
        self.btn_reset = QPushButton("손댄 것 되돌리기")
        self.btn_reset.setToolTip("이 상자의 위치·크기 수정을 모두 지우고 자동 결과로 돌아갑니다 (지운 구간은 유지)")
        self.btn_reset.clicked.connect(lambda: self._track_edit("reset"))
        self.assign_combo = QComboBox()
        self.assign_btn = QPushButton("인물 바꾸기")
        self.assign_btn.clicked.connect(lambda: self._track_edit("assign"))
        for a, b in ((self.btn_del_frame, self.btn_del_range), (self.btn_del_track, self.btn_split)):
            row = QHBoxLayout()
            row.addWidget(a)
            row.addWidget(b)
            bv.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.assign_combo, 1)
        row.addWidget(self.assign_btn)
        bv.addLayout(row)
        bv.addWidget(self.btn_reset)
        self.track_btns = [self.btn_del_frame, self.btn_del_range, self.btn_del_track, self.btn_split,
                           self.btn_reset, self.assign_combo, self.assign_btn]

        self.right = QWidget()
        rv = QVBoxLayout(self.right)
        rv.setContentsMargins(4, 8, 8, 8)
        rv.addWidget(base_box)
        rv.addWidget(box_box)
        rv.addWidget(seg_box, 1)
        self.seg_box = seg_box
        self.base_box = base_box

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(self.right)
        split.setSizes([260, 860, 340])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

    def _build_status(self):
        self.status_label = QLabel("")
        self.progress = QProgressBar(maximumWidth=260, visible=False)
        self.cancel_btn = QPushButton("취소", visible=False)
        self.cancel_btn.clicked.connect(lambda: self.worker and self.worker.cancel())
        sb = self.statusBar()
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.cancel_btn)

    def _build_shortcuts(self):
        for key, fn in [("Space", self.toggle_play), ("Left", lambda: self.step(-1)), ("Right", lambda: self.step(1)),
                        ("Shift+Left", lambda: self.step(-round(self.fps))),
                        ("Shift+Right", lambda: self.step(round(self.fps))),
                        ("I", self.mark_in), ("O", self.mark_out),
                        ("Backspace", lambda: self._track_edit("track")), ("Delete", lambda: self._track_edit("track")),
                        ("S", lambda: self._track_edit("split"))]:
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
        self.right.setEnabled(has_project)
        self.base_box.setEnabled(has_project and self.selected is not None)
        self.seg_box.setEnabled(has_project and self.selected not in (None, ALL))
        self.goto_btn.setEnabled(self.selected not in (None, ALL))
        self.name_edit.setEnabled(self.selected not in (None, ALL))
        has_track = has_project and self.sel_track is not None and self.sel_track in self.project.tracks
        for b in self.track_btns:
            b.setEnabled(has_track)
        picked = self._picked_persons()
        self.merge_btn.setEnabled(len(picked) >= 2)
        self.del_person_btn.setEnabled(bool(picked))

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
        self.sel_track = None
        self.n_frames, self.fps = max(1, info.n_frames), info.fps
        self.frame = 0
        self.timeline.mark_in = self.timeline.mark_out = None
        self.timeline.set_data(self.n_frames, self.fps, [])
        self.timeline.set_person([], [])
        self.persons.clear()
        self.setWindowTitle(f"BlurFace — {Path(path).name}")
        project = Project.load(path)
        if project:
            self._set_project(project)
            self.status_label.setText(f"저장된 분석을 불러왔습니다 · 인물 {len(project.persons)}명")
        else:
            self._start_analysis(path)
        self.seek(0)
        self._update_enabled()

    def reanalyze(self):
        if not self.source:
            return
        if self.project and QMessageBox.question(
                self, "다시 분석",
                "얼굴을 처음부터 다시 찾습니다. 인물 번호가 바뀌고 고친 상자·효과 설정은 새로 시작합니다.\n\n"
                "지금 상태는 자동으로 백업되며, 언제든 '이전 상태로 되돌리기'로 돌아올 수 있습니다. 계속할까요?") \
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
        self._run_worker(w, "분석 중… (분석하는 동안에도 영상을 볼 수 있습니다)",
                         prep="분석 준비 중… (얼굴 인식 모델 불러오는 중, 몇 초 걸립니다)")

    def _on_analyzed(self, project: Project):
        self._set_project(project)
        self.status_label.setText(f"분석 완료 · 인물 {len(project.persons)}명 · 컷 {len(project.cuts)}개 "
                                  f"({project.timings.get('total_analyze', 0):.0f}초)")

    def _set_project(self, project: Project):
        self.project = project
        self.sel_track = None
        self._undo.clear()
        self._redo.clear()
        self._last_state = project.edit_state()
        self._update_review()
        self.n_frames, self.fps = project.n_frames, project.video.fps
        if self.source:
            self.source.set_pts(project.pts)
        self.timeline.set_data(self.n_frames, self.fps, project.cuts)
        self._fill_persons()
        self.persons.setCurrentRow(0)
        self.seek(min(self.frame, self.n_frames - 1))
        self._update_enabled()

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

    # ---------- 인물 목록 / 설정 ----------
    def _fill_persons(self):
        p = self.project
        current = self.selected
        self.persons.blockSignals(True)
        self.persons.clear()
        item = QListWidgetItem(f"모든 인물 기본 효과\n{effect_text(p.default_effect)}")
        item.setData(Qt.ItemDataRole.UserRole, ALL)
        self.persons.addItem(item)
        for pid, person in sorted(p.persons.items()):
            secs = len(p.person_frames(pid)) / p.video.fps
            eff = effect_text(person.effect) if person.effect else f"기본 ({effect_text(p.default_effect)})"
            extra = f" · 구간 {len(person.segments)}" if person.segments else ""
            warn = "  ⚠ 확인 필요" if p.needs_review(pid) else ""
            it = QListWidgetItem(f"#{pid} {person.name}{warn}\n{eff}{extra} · {secs:.1f}초")
            face = p.dir / "faces" / f"{pid}.jpg"
            if face.exists():
                it.setIcon(QIcon(QPixmap(str(face))))
            it.setData(Qt.ItemDataRole.UserRole, pid)
            if p.needs_review(pid):
                it.setForeground(QColor("#f0b429"))
            self.persons.addItem(it)
        self.persons.blockSignals(False)
        for i in range(self.persons.count()):
            if self.persons.item(i).data(Qt.ItemDataRole.UserRole) == current:
                self.persons.setCurrentRow(i)
                break

    def _on_person_selected(self, item, _prev=None):
        if not self.project:
            return
        if item is None:
            self.persons.setCurrentRow(0)
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        self.selected = pid
        p = self.project
        if self.sel_track in p.tracks and p.tracks[self.sel_track].person != pid and pid != ALL:
            self.sel_track = None
        if pid == ALL:
            self.base_picker.allow_inherit = False
            self.base_picker.kind.model().item(0).setEnabled(False)
            self.base_picker.set_effect(p.default_effect)
            self.name_edit.setText("")
            self.info_label.setText("인물별 효과를 따로 정하지 않은 사람에게 적용됩니다.")
            self.timeline.set_person([], [])
            self._fill_segments([])
        else:
            self.base_picker.kind.model().item(0).setEnabled(True)
            person = p.persons[pid]
            self.base_picker.set_effect(person.effect)
            self.name_edit.setText(person.name)
            frames = p.person_frames(pid)
            self.info_label.setText(
                f"등장 {len(frames) / p.video.fps:.1f}초 · 트랙 {len(person.tracks)}개"
                + (" · ⚠ 점수가 낮거나 아주 짧게 나와서 얼굴이 아닐 수 있습니다." if p.needs_review(pid) else ""))
            self.timeline.set_person(self._runs(frames), person.segments)
            self._fill_segments(person.segments)
        self._fill_assign()
        self._update_enabled()
        self.refresh_frame()

    @staticmethod
    def _runs(frames: list[int]) -> list[tuple[int, int]]:
        runs = []
        for f in frames:
            if runs and f <= runs[-1][1] + 1:
                runs[-1][1] = f
            else:
                runs.append([f, f])
        return [(a, b + 1) for a, b in runs]

    def _fill_segments(self, segments: list[dict]):
        self.seg_table.setRowCount(len(segments))
        for r, seg in enumerate(segments):
            for c, text in enumerate([fmt_time(self.project.time_of(seg["start"])),
                                      fmt_time(self.project.time_of(seg["end"])), effect_text(seg["effect"])]):
                self.seg_table.setItem(r, c, QTableWidgetItem(text))

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
        return {"type": "image", "value": str(dst)}

    def _changed(self, track_changed: bool = False):
        """모든 수정 뒤에 부른다: 실행 취소 기록 → 저장 → 화면 갱신."""
        if self._last_state is not None:
            self._undo.append(self._last_state)
            del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._last_state = self.project.edit_state()
        self._after_edit(track_changed)

    def _after_edit(self, track_changed: bool = True):
        self.project.save()
        if track_changed:
            self._update_review()
        if self.selected not in (None, ALL) and self.selected not in self.project.persons:
            self.selected = ALL
        if self.sel_track is not None and self.sel_track not in self.project.tracks:
            self.sel_track = None
        self._fill_persons()
        self._on_person_selected(self.persons.currentItem())

    def undo(self):
        self._step_history(self._undo, self._redo, "실행 취소")

    def redo(self):
        self._step_history(self._redo, self._undo, "다시 실행")

    def _step_history(self, src: list, dst: list, what: str):
        if not self.project or not src:
            return
        dst.append(self.project.edit_state())
        state = src.pop()
        self.project.restore_state(state)
        self._last_state = self.project.edit_state()
        self._after_edit()
        self.status_label.setText(what)

    def _on_base_effect(self):
        if not self.project or self.selected is None:
            return
        e = self._import_asset(self.base_picker.effect())
        if self.selected == ALL:
            if e:
                self.project.default_effect = e
        else:
            self.project.persons[self.selected].effect = e
        self._changed()

    def _on_name(self):
        if self.project and self.selected not in (None, ALL):
            name = self.name_edit.text().strip() or f"인물 {self.selected}"
            if name != self.project.persons[self.selected].name:
                self.project.persons[self.selected].name = name
                self._changed()

    def _goto_person(self):
        if self.project and self.selected not in (None, ALL) and self.timeline.presence:
            self.seek(self.timeline.presence[0][0])

    def mark_in(self):
        self.timeline.mark_in = self.frame
        self.in_label.setText(fmt_time(self._time(self.frame)))
        self.timeline.update()

    def mark_out(self):
        self.timeline.mark_out = self.frame
        self.out_label.setText(fmt_time(self._time(self.frame)))
        self.timeline.update()

    def _add_segment(self):
        if not self.project or self.selected in (None, ALL):
            return
        a, b = self.timeline.mark_in, self.timeline.mark_out
        if a is None or b is None or a == b:
            QMessageBox.information(self, "구간 효과", "시작(I)과 끝(O) 위치를 먼저 정해 주세요.")
            return
        a, b = min(a, b), max(a, b) + 1  # 끝 프레임까지 포함
        self.project.add_segment(self.selected, a, b, self._import_asset(self.seg_picker.effect()))
        self.timeline.mark_in = self.timeline.mark_out = None
        self.in_label.setText("—")
        self.out_label.setText("—")
        self._changed()

    def _delete_segment(self):
        rows = sorted({i.row() for i in self.seg_table.selectedIndexes()}, reverse=True)
        if not rows or self.selected in (None, ALL):
            return
        segs = self.project.persons[self.selected].segments
        for r in rows:
            del segs[r]
        self._changed()

    def _goto_segment(self, row: int):
        if self.selected not in (None, ALL):
            self.seek(self.project.persons[self.selected].segments[row]["start"])

    # ---------- 상자 수정 ----------
    def _picked_persons(self) -> list[int]:
        return sorted(pid for it in self.persons.selectedItems()
                      if (pid := it.data(Qt.ItemDataRole.UserRole)) not in (None, ALL))

    def _select_person(self, pid: int):
        for i in range(self.persons.count()):
            if self.persons.item(i).data(Qt.ItemDataRole.UserRole) == pid:
                self.persons.setCurrentRow(i)
                return

    def _fill_assign(self):
        self.assign_combo.clear()
        p = self.project
        cur = p.tracks[self.sel_track].person if self.sel_track in p.tracks else None
        for pid, person in sorted(p.persons.items()):
            if pid != cur:
                self.assign_combo.addItem(f"#{pid} {person.name}", pid)
        self.assign_combo.addItem("새 인물", None)
        if self.sel_track in p.tracks:
            t = p.tracks[self.sel_track]
            kind = "직접 그림" if t.auto is None else "자동"
            edits = f" · 손댄 프레임 {len(t.keys)}" if t.keys else ""
            self.track_label.setText(f"인물 #{t.person} · 상자 {self.sel_track} ({kind}){edits}")
        else:
            self.track_label.setText("선택한 상자 없음 — 미리보기에서 상자를 클릭하세요")

    def _save_face(self, pid: int, box: list[float]):
        """새로 생긴 인물의 목록용 얼굴 사진 (현재 프레임에서)."""
        img = self.source.read(self.frame) if self.source else None
        if img is None:
            return
        k = self.source.scale
        faces = self.project.dir / "faces"
        faces.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(faces / f"{pid}.jpg"), face_crop(img, [x * k for x in box[:4]]))

    def _on_box_clicked(self, tid):
        self.sel_track = tid
        if tid is not None and tid in self.project.tracks:
            pid = self.project.tracks[tid].person
            if pid != self.selected:
                self._select_person(pid)  # 인물 패널도 그 사람으로
                return
        self._fill_assign()
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
            pid = self.selected if self.selected not in (None, ALL) else None
            if pid is not None and any(p.tracks[tid].person == pid for tid, _b, _s in p.boxes_by_frame().get(self.frame, [])):
                pid = None
            self.sel_track = p.add_manual_track(self.frame, box, pid)
            new_pid = p.tracks[self.sel_track].person
            if new_pid != pid:
                self._save_face(new_pid, box)
            self.selected = new_pid
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
            f = self.frame if self.frame in boxes else min(boxes, default=None)
            if f is not None and f == self.frame:
                self._save_face(new_pid, boxes[f][0])
        self.selected = new_pid

    def merge_selected(self):
        pids = self._picked_persons()
        if len(pids) < 2:
            return
        self.project.merge_persons(pids[0], pids[1:])
        self.selected = pids[0]
        self.status_label.setText(f"인물 {len(pids)}명을 #{pids[0]}로 합쳤습니다")
        self._changed(track_changed=True)

    def delete_selected_persons(self):
        pids = self._picked_persons()
        if not pids:
            return
        for pid in pids:
            self.project.remove_person(pid)
        self.selected = ALL
        self.status_label.setText(f"인물 {len(pids)}명을 지웠습니다 (⌘Z로 되돌리기)")
        self._changed(track_changed=True)

    # ---------- 확인 지점 ----------
    def _update_review(self):
        self.review = self.project.review_points() if self.project else []
        self.timeline.review = [f for f, _ in self.review]
        self.timeline.update()

    def next_review(self):
        if not self.review:
            return
        nxt = next(((f, why) for f, why in self.review if f > self.frame), self.review[0])
        self.pause()
        if not self.act_boxes.isChecked():
            self.act_boxes.setChecked(True)
            self._toggle_boxes(True)
        self.seek(nxt[0])
        i = self.review.index(nxt) + 1
        self.status_label.setText(f"확인 지점 {i}/{len(self.review)}: {nxt[1]}")

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
            self.view.set_boxes([(tid, f"#{self.project.tracks[tid].person}", grow(b), src)
                                 for tid, b, src in per.get(self.frame, [])], self.sel_track)
        self.view.set_image(img)
        self.timeline.set_pos(self.frame)
        self.time_label.setText(f"{fmt_time(self._time(self.frame))} / {fmt_time(self._time(self.n_frames - 1))}"
                                f"  ·  {self.frame}프레임")

    def toggle_play(self):
        if self.play_timer.isActive():
            self.pause()
        elif self.source:
            if self.frame >= self.n_frames - 1:
                self.frame = 0
            self._play_start = (time.perf_counter(), self.frame)
            self.play_timer.start()
            self.play_btn.setText("❚❚")

    def pause(self):
        self.play_timer.stop()
        self.play_btn.setText("▶")

    def _tick(self):
        t0, f0 = self._play_start
        target = f0 + int((time.perf_counter() - t0) * self.fps)
        if target >= self.n_frames:
            self.pause()
            return
        if target != self.frame:
            self.frame = target
            self.refresh_frame()

    def _toggle_boxes(self, on: bool):
        self.view.edit = on
        self.view.unsetCursor()
        self.refresh_frame()

    # ---------- 내보내기 ----------
    def export(self):
        if not self.project or self.worker:
            return
        self.pause()
        src = Path(self.project.video.path)
        default = str(src.with_name(src.stem + "_mosaic.mp4"))
        out, _ = QFileDialog.getSaveFileName(self, "내보내기", default, "MP4 영상 (*.mp4)")
        if not out:
            return
        w = ExportWorker(self.project, out)
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


def apply_dark(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [(QPalette.ColorRole.Window, "#1f2228"), (QPalette.ColorRole.WindowText, "#e6e8eb"),
                        (QPalette.ColorRole.Base, "#16181d"), (QPalette.ColorRole.AlternateBase, "#22252c"),
                        (QPalette.ColorRole.Text, "#e6e8eb"), (QPalette.ColorRole.Button, "#2a2e36"),
                        (QPalette.ColorRole.ButtonText, "#e6e8eb"), (QPalette.ColorRole.Highlight, "#3d6fd9"),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, "#2a2e36"),
                        (QPalette.ColorRole.ToolTipText, "#e6e8eb"), (QPalette.ColorRole.PlaceholderText, "#6b7280")]:
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5c626e"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#5c626e"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#5c626e"))
    app.setPalette(pal)
    app.setStyleSheet("QGroupBox { font-weight: 600; margin-top: 14px; padding-top: 6px; }"
                      "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
                      "QListWidget::item { padding: 6px; }")


def main(argv: list[str] | None = None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("BlurFace")
    apply_dark(app)
    win = MainWindow()
    win.show()
    files = [a for a in argv[1:] if Path(a).exists()]
    if files:
        QTimer.singleShot(0, lambda: win.open_video(files[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
