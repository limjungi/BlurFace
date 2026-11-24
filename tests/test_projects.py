import json

from blurface import projects


def _video(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def _save(d, video):
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(json.dumps({"video": {"path": str(video), "n_frames": 300, "fps": 30.0},
                                                "persons": {"0": {}, "1": {}}}))


def test_new_project_goes_to_library(tmp_path):
    v = _video(tmp_path / "a" / "회의.mp4")
    d = projects.dir_for(v)
    assert d == projects.root() / "회의.blurface" and not (v.parent / "회의.blurface").exists()


def test_same_name_different_videos_get_own_folders(tmp_path):
    v1, v2 = _video(tmp_path / "a" / "clip.mp4"), _video(tmp_path / "b" / "clip.mp4")
    d1 = projects.dir_for(v1)
    _save(d1, v1)
    projects._found.clear()
    d2 = projects.dir_for(v2)
    assert d2 != d1 and d2.name == "clip 2.blurface"
    projects._found.clear()
    assert projects.dir_for(v1) == d1  # 다시 찾을 때도 같은 폴더


def test_legacy_folder_next_to_video_moves_into_library(tmp_path):
    v = _video(tmp_path / "a" / "old.mp4")
    _save(v.with_name("old.blurface"), v)
    d = projects.dir_for(v)
    assert d.parent == projects.root() and (d / "project.json").exists()
    assert not v.with_name("old.blurface").exists()


def test_list_relink_and_trash(tmp_path, monkeypatch):
    v = _video(tmp_path / "a" / "trip.mp4")
    d = projects.dir_for(v)
    _save(d, v)
    [m] = projects.list_projects()
    assert m["name"] == "trip" and m["video_exists"] and m["persons"] == 2 and m["duration"] == 10
    moved = tmp_path / "b" / "trip.mp4"
    moved.parent.mkdir()
    v.rename(moved)
    assert not projects.list_projects()[0]["video_exists"]
    projects.relink(d, moved)
    assert projects.list_projects()[0]["video_exists"] and projects.dir_for(moved) == d
    assert json.loads((d / "project.json").read_text())["video"]["path"] == str(moved.resolve())
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".Trash").mkdir(parents=True)
    projects.trash(d)
    assert projects.list_projects() == [] and moved.exists()  # 원본 영상은 그대로


def test_set_root_moves_projects(tmp_path, monkeypatch):
    monkeypatch.delenv("BLURFACE_PROJECTS")
    monkeypatch.setattr(projects, "DEFAULT_ROOT", str(tmp_path / "Movies" / "BlurFace"))
    v = _video(tmp_path / "a" / "x.mp4")
    d = projects.dir_for(v)
    _save(d, v)
    assert projects.set_root(tmp_path / "new", move=True) == []
    assert projects.root() == tmp_path / "new" and [m["name"] for m in projects.list_projects()] == ["x"]
    assert projects.dir_for(v).parent == tmp_path / "new"
