import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from blurface.gui.app import MainWindow  # noqa: E402
from blurface.gui.widgets import ALL, EffectPicker, preset_effect  # noqa: E402
from blurface.project import Project  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "test_videos/sample_fhd_cuts.mp4"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("effect", [
    {"type": "mosaic", "value": 12.0}, {"type": "blur", "value": 45.0}, {"type": "solid", "value": "#ff0000"},
    {"type": "sticker", "value": "heart"}, {"type": "none", "value": None},
    {"type": "blur", "value": 60.0, "shape": "ellipse", "feather": 20.0, "scale": 130.0},
    {"type": "mosaic", "value": 10.0, "shape": "rounded"}, {"type": "sticker", "value": "smile", "scale": 80.0},
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


@pytest.fixture
def opened(app, tmp_path):
    """샘플 영상과 분석 결과를 임시 폴더에 복사해 연다 (원본 프로젝트 파일을 건드리지 않게)."""
    import shutil
    if not (SAMPLE.exists() and (SAMPLE.with_name(SAMPLE.stem + ".blurface") / "project.json").exists()):
        pytest.skip("샘플 영상·분석 결과 없음")
    video = tmp_path / SAMPLE.name
    shutil.copy(SAMPLE, video)
    shutil.copytree(SAMPLE.with_name(SAMPLE.stem + ".blurface"), tmp_path / (SAMPLE.stem + ".blurface"))
    w = MainWindow()
    w.resize(1400, 860)
    w.show()
    w.open_video(str(video))
    app.processEvents()
    yield w
    w.close()


def drag(app, view, a, b):
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPointF(*a).toPoint())
    QTest.mouseMove(view, QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2).toPoint())
    QTest.mouseMove(view, QPointF(*b).toPoint())
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPointF(*b).toPoint())
    app.processEvents()


def first_box(w):
    per = w.project.boxes_by_frame()
    f = min(per)
    w.seek(f)
    tid, b, _ = per[f][0]
    return f, tid


def test_drag_box_moves_it_and_undo_restores(app, opened):
    from blurface.effects import grow
    w = opened
    w.act_boxes.trigger()
    f, tid = first_box(w)
    before = w.project.track_boxes(tid)[f][0][:4]
    r = w.view.to_screen(grow(before))
    drag(app, w.view, (r.center().x(), r.center().y()), (r.center().x() + 40, r.center().y()))
    assert w.sel_track == tid
    after = w.project.track_boxes(tid)[f]
    assert after[1] == "manual" and after[0][0] > before[0] + 10
    w.undo()
    assert w.project.track_boxes(tid)[f][0][:4] == before
    w.redo()
    assert w.project.track_boxes(tid)[f][1] == "manual"


def test_draw_new_box_creates_person_and_continues_track(app, opened):
    w = opened
    w.act_boxes.trigger()
    w.select_person(ALL)  # 모든 인물 → 새 인물로 만들어져야 함
    n_persons = len(w.project.persons)
    w.seek(5)
    a = w.view._area()
    drag(app, w.view, (a.x() + 20, a.y() + 20), (a.x() + 80, a.y() + 90))
    tid = w.sel_track
    assert tid is not None and w.project.tracks[tid].auto is None
    assert len(w.project.persons) == n_persons + 1
    assert (w.project.dir / "faces" / f"{w.project.tracks[tid].person}.jpg").exists()
    w.seek(15)
    drag(app, w.view, (a.x() + 120, a.y() + 20), (a.x() + 180, a.y() + 90))
    assert w.sel_track == tid and sorted(w.project.track_boxes(tid)) == list(range(5, 16))


def test_delete_split_merge_and_review(app, opened):
    w = opened
    p = w.project
    f, tid = first_box(w)
    w.sel_track = tid
    w._track_edit("track")
    assert p.track_boxes(tid) == {}
    w.undo()
    assert p.track_boxes(tid)
    # 나누기 → 새 인물, 다시 합치기
    frames = sorted(p.track_boxes(tid))
    old_pid = p.tracks[tid].person
    person_total = len(p.person_frames(old_pid))
    w.sel_track = tid
    w.seek(frames[len(frames) // 2])
    w._track_edit("split")
    new_pid = p.tracks[w.sel_track].person
    assert new_pid != old_pid and new_pid in p.persons
    w.select_person(old_pid)
    w.select_person(new_pid, multi=True)
    assert w.picked == {old_pid, new_pid} and w.merge_btn.isVisibleTo(w)
    w.merge_selected()
    assert new_pid not in p.persons and len(p.person_frames(old_pid)) == person_total
    # 저장한 수정이 다시 열어도 유지 (복사한 위치에 저장됐는지도 확인)
    assert str(p.dir).startswith(str(opened_dir := Path(p.video.path).parent))
    q = Project.load(p.video.path)
    assert len(q.person_frames(old_pid)) == person_total and opened_dir.exists()
    # 확인 지점 이동
    if w.review:
        w.seek(0)
        w.next_review()
        assert w.frame == next((rf for rf, _p, _r in w.review if rf > 0), w.review[0][0])


def test_restore_backup_brings_back_settings(app, opened):
    w = opened
    p = w.project
    pid = min(p.persons)
    p.persons[pid].effect = {"type": "sticker", "value": "heart"}
    w._changed()
    path = p.video.path
    backup = Project.backup(path)
    p.persons[pid].effect = None  # 다시 분석으로 설정이 사라졌다고 가정
    w._changed()
    w.restore_backup(backup)
    assert w.project.persons[pid].effect == {"type": "sticker", "value": "heart"}
    assert w.act_restore.isEnabled()


def test_timeline_rows_show_default_blur_and_person_effect(app, opened):
    w = opened
    p = w.project
    p.default_effect = {"type": "blur", "value": 30.0, "shape": "ellipse", "feather": 20.0}
    w._changed()
    rows = w.timeline.rows
    assert rows[0].pid == ALL and len(rows) == len(p.persons) + 1
    pid = rows[1].pid
    assert rows[1].inherited and rows[1].effect["type"] == "blur"  # 기본 블러가 보임
    w._apply_preset(pid, "heart")
    row = next(r for r in w.timeline.rows if r.pid == pid)
    assert not row.inherited and row.effect == {"type": "sticker", "value": "heart"}
    assert w.selected == pid and w.picker.key == "heart"


def test_drag_on_person_row_adds_segment(app, opened):
    w = opened
    pid = w.timeline.rows[1].pid
    w.add_segment(pid, 10, 21, preset_effect("smile"))
    assert w.project.persons[pid].segments[-1] == {"start": 10, "end": 21, "effect": {"type": "sticker", "value": "smile"}}
    assert w.project.effect_for(pid, 15)["value"] == "smile"
    w.undo()
    assert not w.project.persons[pid].segments


def test_timeline_drag_emits_range(app, opened):
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    w = opened
    tl = w.timeline
    got = []
    tl.range_picked.disconnect()
    tl.range_picked.connect(lambda pid, a, b, _pos: got.append((pid, a, b)))
    y = tl.RULER + tl.ROW * 1 + tl.ROW // 2 - tl.scroll.value()
    x0, x1 = tl._x(100), tl._x(200)
    QTest.mousePress(tl, Qt.MouseButton.LeftButton, pos=QPointF(x0, y).toPoint())
    QTest.mouseMove(tl, QPointF(x0 + 20, y).toPoint())
    QTest.mouseMove(tl, QPointF(x1, y).toPoint())
    QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, pos=QPointF(x1, y).toPoint())
    assert got and got[0][0] == tl.rows[1].pid and abs(got[0][1] - 100) <= 2 and abs(got[0][2] - 201) <= 2
