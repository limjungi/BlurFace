import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from blurface.gui.app import MainWindow  # noqa: E402
from blurface.gui.widgets import EffectPicker  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "test_videos/sample_fhd_cuts.mp4"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("effect", [
    {"type": "mosaic", "value": 12.0}, {"type": "blur", "value": 45.0}, {"type": "solid", "value": "#ff0000"},
    {"type": "sticker", "value": "heart"}, {"type": "none", "value": None},
])
def test_effect_picker_roundtrip(app, effect):
    p = EffectPicker()
    p.set_effect(effect)
    assert p.effect() == effect


def test_effect_picker_inherit(app):
    p = EffectPicker(allow_inherit=True)
    p.set_effect(None)
    assert p.effect() is None


def test_runs_groups_consecutive_frames():
    assert MainWindow._runs([1, 2, 3, 7, 8, 20]) == [(1, 4), (7, 9), (20, 21)]


@pytest.mark.skipif(not (SAMPLE.exists() and (SAMPLE.with_name(SAMPLE.stem + ".blurface") / "project.json").exists()),
                    reason="샘플 영상·분석 결과 없음")
def test_open_select_and_add_segment(app, tmp_path):
    w = MainWindow()
    w.open_video(str(SAMPLE))
    assert w.project is not None and w.persons.count() == len(w.project.persons) + 1
    w.persons.setCurrentRow(1)
    pid = w.selected
    before = list(w.project.persons[pid].segments)
    try:
        w.seek(10)
        w.mark_in()
        w.seek(20)
        w.mark_out()
        w.seg_picker.set_effect({"type": "sticker", "value": "heart"})
        w._add_segment()
        segs = w.project.persons[pid].segments
        assert segs[-1] == {"start": 10, "end": 21, "effect": {"type": "sticker", "value": "heart"}}
        assert w.project.effect_for(pid, 15)["value"] == "heart"
        assert w.timeline.mark_in is None  # 추가 후 표시 초기화
    finally:
        w.project.persons[pid].segments = before
        w.project.save()
        w.close()
