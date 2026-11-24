import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

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
    # 샘플 분석 결과: 영상 옆(예전 방식) 또는 실제 보관함
    src = next((d for d in (SAMPLE.with_name(SAMPLE.stem + ".blurface"),
                            Path("~/Movies/BlurFace").expanduser() / (SAMPLE.stem + ".blurface"))
                if (d / "project.json").exists()), None)
    if not SAMPLE.exists() or src is None:
        pytest.skip("샘플 영상·분석 결과 없음")
    video = tmp_path / SAMPLE.name
    shutil.copy(SAMPLE, video)
    shutil.copytree(src, tmp_path / (SAMPLE.stem + ".blurface"))  # 영상 옆에 두면 열 때 보관함으로 옮겨짐
    w = MainWindow()
    w.resize(1400, 860)
    w.show()
    w.open_video(str(video))
    # 샘플 프로젝트에 남아 있을 수 있는 설정을 지우고 깨끗한 상태에서 시작
    from blurface.project import DEFAULT_EFFECT
    pr = w.project
    pr.default_effect = dict(DEFAULT_EFFECT)
    for person in pr.persons.values():
        person.effect, person.segments, person.splits = None, [], []
    pr.save()
    w._set_project(Project.load(video))
    w._open_group(True)  # 기존 테스트는 사람별 줄 기준
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


def _press(tl, x, y, release_x=None):
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    QTest.mousePress(tl, Qt.MouseButton.LeftButton, pos=QPointF(x, y).toPoint())
    if release_x is not None:
        QTest.mouseMove(tl, QPointF((x + release_x) / 2, y).toPoint())
        QTest.mouseMove(tl, QPointF(release_x, y).toPoint())
    QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, pos=QPointF(release_x or x, y).toPoint())


def _row_of(tl, pid):
    return next(i for i, r in enumerate(tl.rows) if r.pid == pid)


def _row_y(tl, i):
    return tl.RULER + tl.ROW * i + tl.ROW // 2 - tl.scroll.value()


def test_blade_then_piece_effect(app, opened):
    w = opened
    p = w.project
    pid = w.timeline.rows[1].pid
    w.select_person(pid)
    w.seek(100)
    w.blade()
    w.seek(200)
    w.blade()
    assert p.persons[pid].splits == [100, 200] and w.piece == (200, p.n_frames)  # 재생 위치가 든 조각 선택
    w._on_piece_clicked(pid, 150)
    w._apply_preset(pid, "heart", w.piece)
    assert p.effect_for(pid, 150)["value"] == "heart" and p.effect_for(pid, 99)["type"] == "blur"
    assert w.picker.key == "heart"
    w.undo()
    assert p.effect_for(pid, 150)["type"] == "blur"


def test_drag_split_line_resizes_piece(app, opened):
    w = opened
    p = w.project
    tl = w.timeline
    pid = tl.rows[1].pid
    p.add_segment(pid, 100, 200, preset_effect("smile"))
    w.select_person(pid)
    w._changed()  # 따로 정한 사람이 되어 줄 위치가 바뀜 (선택한 사람 줄은 보이게 스크롤)
    got = []
    tl.split_moved.connect(lambda *a: got.append(a))
    _press(tl, tl._x(200), _row_y(tl, _row_of(tl, pid)), tl._x(260))
    assert got and got[0][:2] == (pid, 200) and abs(got[0][2] - 260) <= 2
    assert p.persons[pid].segments[0]["end"] == p.persons[pid].splits[1]


def test_zoom_keeps_anchor_and_pans(app, opened):
    tl = opened.timeline
    x = tl._x(300)
    tl.zoom_by(4, x)
    assert tl.zoom == 4 and abs(tl._frame_at(x) - 300) <= 2 and tl.hscroll.isVisible()
    tl.zoom_by(0.01)
    assert tl.zoom == 1 and tl.offset == 0


def test_double_click_name_renames(app, opened):
    from PySide6.QtTest import QTest
    w = opened
    tl = w.timeline
    pid = tl.rows[1].pid
    assert tl.rows[1].name == f"인물 {pid + 1}"  # 1번부터
    tl.start_rename(1)
    tl.editor.setText("철수")
    QTest.keyClick(tl.editor, Qt.Key.Key_Return)
    assert w.project.persons[pid].name == "철수"


def test_rest_group_collapses_and_only_rest_changes(app, opened, monkeypatch):
    w = opened
    p = w.project
    tl = w.timeline
    w.select_person(ALL)
    w._open_group(False)
    n = len(p.persons)
    assert [r.pid for r in tl.rows] == [ALL] and tl.rows[0].name == f"모든 인물 {n}명"
    assert tl.rows[0].presence  # 묶음 줄에도 등장 막대
    pid = sorted(p.persons)[1]
    w._apply_preset(pid, "heart")  # 이 사람만 따로 → 묶음에서 빠져 자기 줄
    w._open_group(False)
    assert tl.rows[0].name == f"나머지 {n - 1}명" and [r.pid for r in tl.rows] == [ALL, pid]
    w.select_person(ALL)
    w.set_effect(ALL, preset_effect("mosaic"))  # 나머지에만
    assert p.default_effect["type"] == "mosaic" and p.persons[pid].effect["value"] == "heart"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    w.reset_all_to_rest()
    assert p.persons[pid].effect is None and len(tl.rows) == 1


def test_disclosure_click_expands_group(app, opened):
    w = opened
    tl = w.timeline
    w.select_person(ALL)
    w._open_group(False)
    _press(tl, 10, _row_y(tl, 0))
    assert w.group_open and len(tl.rows) == len(w.project.persons) + 1 and tl.rows[1].member


def test_click_face_in_preview_selects_person(app, opened):
    w = opened
    p = w.project
    w.select_person(ALL)
    w._open_group(False)
    w.seek(100)
    tid, _name, box, _src = w.view.boxes[0]
    r = w.view.to_screen(box)
    from PySide6.QtTest import QTest
    QTest.mouseClick(w.view, Qt.MouseButton.LeftButton, pos=r.center().toPoint())
    pid = p.tracks[tid].person
    assert w.selected == pid and w.group_open  # 묶음 안 사람이면 펼쳐서 보여줌
    assert any(r.pid == pid for r in w.timeline.rows)
    w._apply_preset(pid, "smile")
    assert p.effect_for(pid)["value"] == "smile" and w.selected == pid


def test_image_library_keeps_uploads(app, tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from blurface import library
    monkeypatch.setenv("BLURFACE_HOME", str(tmp_path / "home"))
    img = tmp_path / "me.png"
    cv2.imwrite(str(img), np.full((20, 20, 4), 255, np.uint8))
    a = library.add(img)
    assert library.add(img) == a and library.images() == [a]  # 같은 그림은 한 번만
    picker = EffectPicker()
    picker._on_click("image")  # 보관함에 있으면 바로 선택
    assert picker.effect() == {"type": "image", "value": str(a)}
    assert picker.lib_grid.count() == 2  # 그림 1 + 올리기 버튼


def test_fullscreen_hides_panels(app, opened):
    w = opened
    w.toggle_fullscreen()
    assert not w.timeline.isVisible() and not w.inspector.isVisible()
    w._escape()
    assert w.timeline.isVisible()


def test_export_dialog_options(app, opened):
    from blurface.gui.export_dialog import ExportDialog
    dlg = ExportDialog(opened.project)
    assert set(dlg.res_btns) == {"original", "720"}  # FHD 원본보다 작은 것만
    dlg.codec_btns["h264"].setChecked(True)
    dlg.quality_btns["small"].setChecked(True)
    dlg.res_btns["720"].setChecked(True)
    o = dlg.options()
    assert (o.codec, o.quality, o.height) == ("h264", "small", 720)
    assert "MB" in dlg.info.text() and "1280×720" in dlg.info.text()
    assert dlg.out_path().endswith("_mosaic.mp4")


def test_blade_tool_click_and_backspace_removes_part(app, opened):
    w = opened
    p = w.project
    tl = w.timeline
    pid = tl.rows[1].pid
    frames = sorted(p.person_frames(pid))
    a, b = frames[10], frames[40]
    w.act_tool_blade.trigger()
    assert tl.tool == "blade"
    _press(tl, tl._x(a), _row_y(tl, 1))
    _press(tl, tl._x(b), _row_y(tl, _row_of(tl, pid)))
    sp = p.persons[pid].splits
    assert len(sp) == 2 and abs(sp[0] - a) <= 2 and abs(sp[1] - b) <= 2
    w.act_tool_select.trigger()
    w._on_piece_clicked(pid, (a + b) // 2)
    before = len(p.person_frames(pid))
    w.delete_key()
    piece = p.piece_at(pid, (a + b) // 2)
    gone = set(range(*piece)) & set(p.person_frames(pid))
    assert not gone and len(p.person_frames(pid)) < before
    w.undo()
    assert len(p.person_frames(pid)) == before


def test_trim_drag_previews_bar(app, opened):
    tl = opened.timeline
    r = tl.rows[1]
    a, b = r.presence[0]
    tl._drag = {"mode": "trim", "orig": b, "new": b - 20, "row": 1}
    assert tl._preview(r).presence[0] == (a, b - 20)
    tl._drag = None


def test_speed_and_seekbar(app, opened):
    w = opened
    w.set_speed(2.0)
    assert w.speed == 2.0 and w.speed_btns[2.0].isChecked() and not w.speed_btns[1.0].isChecked()
    w.seekbar.seek.emit(300)
    assert w.frame == 300 and w.seekbar.pos == 300


def test_menubar_has_menus_and_actions(app, opened):
    w = opened
    menus = {a.text(): a.menu() for a in w.menuBar().actions()}
    assert list(menus)[:5] == ["파일", "편집", "도구", "재생", "보기"]
    texts = {a.text() for m in menus.values() for a in m.actions()}
    assert {"열기", "내보내기", "실행 취소", "자르기 도구", "재생 / 일시 정지", "2배속", "전체 화면"} <= texts
    menus["재생"].actions()[0].trigger()  # 재생 / 일시 정지
    assert w.play_timer.isActive()
    w.pause()
    w.act_speed[0.5].trigger()
    assert w.speed == 0.5 and w.speed_btns[0.5].isChecked()


def test_notify_only_when_not_looking(app, opened, monkeypatch):
    from blurface.gui import notify as nmod
    sent = []
    monkeypatch.setattr(nmod, "notify", lambda t, x, sound=True: sent.append(t))
    w = opened
    w.act_notify.setChecked(True)
    monkeypatch.setattr(w, "isActiveWindow", lambda: True)
    w._notify("내보내기 완료", "a.mp4")
    assert sent == []
    monkeypatch.setattr(w, "isActiveWindow", lambda: False)
    w._notify("내보내기 완료", "a.mp4")
    assert sent == ["내보내기 완료"]
    w.act_notify.setChecked(False)
    w._notify("내보내기 완료", "a.mp4")
    assert sent == ["내보내기 완료"]
    w.act_notify.setChecked(True)


def test_notify_quotes():
    from blurface.gui.notify import _quote
    assert _quote('a "b" \\c') == '"a \\"b\\" \\\\c"'


def test_sidebar_lists_and_reopens_projects(app, opened, tmp_path, monkeypatch):
    import shutil

    from blurface import projects
    w = opened
    d = w.project.dir
    assert d.parent == projects.root()  # 영상 옆 예전 폴더가 보관함으로 옮겨짐
    assert [m["dir"] for m in w.sidebar.items] == [d] and w.sidebar.list.currentRow() == 0
    assert (d / "cover.jpg").exists()  # 표지 자동 생성
    # 원본 영상을 옮기면 다시 연결해서 열기
    video = Path(w.project.video.path)
    w.project = None
    moved = tmp_path / "moved" / video.name
    moved.parent.mkdir()
    shutil.move(str(video), moved)
    w.sidebar.refresh()
    assert not w.sidebar.items[0]["video_exists"]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("blurface.gui.app.QFileDialog.getOpenFileName", lambda *a, **k: (str(moved), ""))
    w.open_project(w.sidebar.items[0])
    assert w.project is not None and w.project.dir == d and Path(w.project.video.path) == moved


def test_cannot_delete_open_project(app, opened, monkeypatch):
    w = opened
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    w._delete_project(w.sidebar.items[0])
    assert shown and w.project.dir.exists()
