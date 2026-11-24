"""내보내기 창: 형식·화질·해상도 고르기, 예상 용량 표시."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..project import Project
from ..render import RESOLUTIONS, ExportOptions


def _segmented(choices: list[tuple[str, str, str]], current: str) -> tuple[QWidget, QButtonGroup, dict]:
    """(값, 이름, 설명) 버튼 묶음."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    group = QButtonGroup(box)
    btns = {}
    for value, name, tip in choices:
        b = QToolButton()
        b.setObjectName("seg")
        b.setCheckable(True)
        b.setText(name)
        b.setToolTip(tip)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setMinimumHeight(30)
        group.addButton(b)
        btns[value] = b
        lay.addWidget(b)
    (btns.get(current) or next(iter(btns.values()))).setChecked(True)
    return box, group, btns


class ExportDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("내보내기")
        self.setMinimumWidth(500)
        self.project = project
        v = project.video
        st = QSettings("BlurFace", "BlurFace")
        short = min(v.width, v.height)

        codecs = [("hevc", "HEVC", "파일이 작고 선명합니다. 아이폰·맥·유튜브 등 대부분 재생"),
                  ("h264", "H.264", "어디서나 재생됩니다 (오래된 기기, 일부 사이트·메신저). 파일이 조금 더 큼")]
        quality = [("high", "원본 수준", "원본과 거의 같은 화질"), ("normal", "보통", "용량 약 절반"),
                   ("small", "작게", "메신저로 보내기 좋은 크기")]
        res = [("original", f"원본 ({v.width}×{v.height})", "원본 해상도 그대로")]
        res += [(str(r), f"{r}p", f"짧은 변 {r}px로 줄이기") for r in RESOLUTIONS if r < short]
        self.codec_box, _, self.codec_btns = _segmented(codecs, st.value("export/codec", "hevc"))
        self.quality_box, _, self.quality_btns = _segmented(quality, st.value("export/quality", "high"))
        self.res_box, _, self.res_btns = _segmented(res, st.value("export/resolution", "original"))
        for btns in (self.codec_btns, self.quality_btns, self.res_btns):
            for b in btns.values():
                b.toggled.connect(self._update)

        src = Path(v.path)
        self.path_edit = QLineEdit(str(src.with_name(src.stem + "_mosaic.mp4")))
        browse = QPushButton("변경…")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)

        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("형식", self.codec_box)
        form.addRow("화질", self.quality_box)
        form.addRow("해상도", self.res_box)
        form.addRow("저장 위치", path_row)

        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("내보내기")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)
        lay.addLayout(form)
        lay.addWidget(self.info)
        lay.addLayout(buttons)
        self._update()

    @staticmethod
    def _value(btns: dict) -> str:
        return next(k for k, b in btns.items() if b.isChecked())

    def options(self) -> ExportOptions:
        r = self._value(self.res_btns)
        return ExportOptions(self._value(self.codec_btns), self._value(self.quality_btns),
                             None if r == "original" else int(r))

    def out_path(self) -> str:
        path = self.path_edit.text().strip()
        return path if path.lower().endswith(".mp4") else path + ".mp4"

    def _update(self, *_):
        p = self.project
        v = p.video
        o = self.options()
        secs = p.time_of(p.n_frames - 1) if p.n_frames else 0
        w, h = o.size(v.width, v.height)
        lines = [f"예상 크기 약 {o.estimate_mb(v, secs):,.0f}MB · {w}×{h}"]
        if v.high_bit and o.codec == "h264":
            lines.append("⚠ HDR(10bit) 영상은 H.264로 내보내면 색이 달라질 수 있어요. HEVC를 추천합니다.")
        self.info.setText("\n".join(lines))

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "저장 위치", self.path_edit.text(), "MP4 영상 (*.mp4)")
        if path:
            self.path_edit.setText(path)

    def _accept(self):
        st = QSettings("BlurFace", "BlurFace")
        o = self.options()
        st.setValue("export/codec", o.codec)
        st.setValue("export/quality", o.quality)
        st.setValue("export/resolution", "original" if o.height is None else str(o.height))
        self.accept()
