"""수동 수정(3단계) 테스트."""

import json

import pytest

from blurface.project import AutoTrack, Person, Project, Track
from blurface.video import VideoInfo


def make(tmp_path, n=100, fps=10.0):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    info = VideoInfo(str(video), 1000, 1000, fps, f"{int(fps)}/1", n, 0, False, "h264", 0, {}, True)
    # 자동 트랙 0: 프레임 0~49, x가 프레임마다 2씩 이동. 자동 트랙 1: 프레임 60~99 고정
    a0 = AutoTrack(list(range(50)), [[f * 2, 0, f * 2 + 10, 10, 0.9] for f in range(50)], ["auto"] * 50)
    a1 = AutoTrack(list(range(60, 100)), [[500, 500, 520, 520, 0.9]] * 40, ["auto"] * 40)
    return Project(info, n, [], {0: Track(0, auto=0), 1: Track(1, auto=1)},
                   {0: Person("A", [0], []), 1: Person("B", [1], [])}, auto={0: a0, 1: a1})


def box(p, tid, f):
    return p.track_boxes(tid)[f][0][:4]


def test_no_edits_returns_auto(tmp_path):
    p = make(tmp_path)
    assert box(p, 0, 10) == [20, 0, 30, 10]
    assert p.track_boxes(0)[10][1] == "auto"


def test_single_key_overrides_frame_and_fades_out(tmp_path):
    p = make(tmp_path)
    p.set_key(0, 20, [40 + 10, 0, 50 + 10, 10])  # 자동보다 x +10
    assert box(p, 0, 20) == [50, 0, 60, 10]
    assert box(p, 0, 22)[0] == pytest.approx(44 + 10 * (1 - 2 / 5))  # fade 0.5초 = 5프레임
    assert box(p, 0, 25)[0] == 50  # 5프레임 지나면 자동 그대로
    assert p.track_boxes(0)[25][1] == "auto"


def test_offset_between_keys_follows_auto_motion(tmp_path):
    p = make(tmp_path)
    p.set_key(0, 10, [20 + 6, 0, 30 + 6, 10])
    p.set_key(0, 20, [40 + 6, 0, 50 + 6, 10])
    for f in range(10, 21):
        assert box(p, 0, f)[0] == pytest.approx(f * 2 + 6)  # 자동 움직임 + 같은 보정
        assert p.track_boxes(0)[f][1] == "manual"


def test_manual_track_interpolates_between_keys(tmp_path):
    p = make(tmp_path)
    tid = p.add_manual_track(10, [0, 0, 10, 10])
    p.set_key(tid, 20, [100, 0, 110, 10])
    assert box(p, tid, 15) == pytest.approx([50, 0, 60, 10])
    assert sorted(p.track_boxes(tid)) == list(range(10, 21))
    assert p.tracks[tid].person not in (0, 1)  # 새 인물
    assert tid in p.persons[p.tracks[tid].person].tracks


def test_remove_range_and_track(tmp_path):
    p = make(tmp_path)
    p.remove_range(0, 10, 20)
    p.remove_range(0, 15, 30)  # 겹치면 합쳐짐
    assert p.tracks[0].removed == [[10, 30]]
    assert 9 in p.track_boxes(0) and 10 not in p.track_boxes(0) and 30 in p.track_boxes(0)
    p.remove_track(1)
    assert p.track_boxes(1) == {}
    assert 70 not in p.boxes_by_frame()


def test_split_and_assign_to_new_person(tmp_path):
    p = make(tmp_path)
    p.set_key(0, 5, [0, 0, 1, 1])
    p.set_key(0, 40, [0, 0, 1, 1])
    new = p.split_track(0, 30)
    assert max(p.track_boxes(0)) == 29 and min(p.track_boxes(new)) == 30
    assert list(p.tracks[0].keys) == [5] and list(p.tracks[new].keys) == [40]
    pid = p.assign_track(new, None)
    assert pid not in (0, 1) and p.persons[pid].tracks == [new]
    assert p.persons[0].tracks == [0]


def test_merge_persons_moves_tracks_and_drops_empty(tmp_path):
    p = make(tmp_path)
    p.merge_persons(0, [1])
    assert 1 not in p.persons
    assert p.persons[0].tracks == [0, 1]
    assert p.tracks[1].person == 0


def test_undo_restore_state(tmp_path):
    p = make(tmp_path)
    state = p.edit_state()
    p.set_key(0, 10, [0, 0, 1, 1])
    p.merge_persons(0, [1])
    p.restore_state(state)
    assert p.tracks[0].keys == {} and 1 in p.persons
    assert box(p, 0, 10) == [20, 0, 30, 10]


def test_review_points_find_interp_and_low_score(tmp_path):
    p = make(tmp_path)
    a = p.auto[0]
    for f in range(10, 15):
        a.sources[f] = "interp"
    for f in range(30, 36):
        a.boxes[f][4] = 0.4
    p._touch(0)
    reasons = {f: why for f, _pid, why in p.review_points()}
    assert 10 in reasons and "끊겨" in reasons[10]
    assert 30 in reasons and "점수" in reasons[30]


def test_load_v2_project_migrates(tmp_path):
    p = make(tmp_path)
    path = p.dir / "project.json"
    p.dir.mkdir(parents=True)
    v2 = {"version": 2, "video": json.loads(json.dumps(p.video.__dict__)), "n_frames": 100, "cuts": [],
          "default_effect": {"type": "mosaic", "value": 8},
          "persons": {"0": {"name": "A", "tracks": [0], "thumb": [], "effect": None, "segments": []}},
          "tracks": {"0": {"person": 0, "frames": [1, 2], "boxes": [[0, 0, 5, 5, 0.9]] * 2, "sources": ["auto"] * 2}},
          "pts": []}
    path.write_text(json.dumps(v2))
    q = Project.load(p.video.path)
    assert q.tracks[0].auto == 0 and q.auto[0].frames == [1, 2]
    assert box(q, 0, 2) == [0, 0, 5, 5]


def test_backup_and_restore_roundtrip(tmp_path):
    p = make(tmp_path)
    assert Project.backup(p.video.path) is None  # 저장된 게 없으면 백업 안 함
    p.persons[0].effect = {"type": "sticker", "value": "heart"}
    p.set_key(0, 10, [0, 0, 5, 5])
    p.save()
    (p.dir / "faces").mkdir()
    (p.dir / "faces" / "0.jpg").write_bytes(b"old")
    b = Project.backup(p.video.path)
    assert "효과 지정 1명" in Project.backup_summary(b) and "고친 상자 1개" in Project.backup_summary(b)
    # 다시 분석했다고 치고 덮어쓰기
    p.persons[0].effect = None
    p.clear_key(0)
    p.save()
    (p.dir / "faces" / "0.jpg").write_bytes(b"new")
    q = Project.restore(p.video.path, b)
    assert q.persons[0].effect == {"type": "sticker", "value": "heart"} and q.tracks[0].keys
    assert (p.dir / "faces" / "0.jpg").read_bytes() == b"old"
    # 되돌리기 직전 상태도 백업돼 있어 다시 돌아갈 수 있음
    latest = Project.backups(p.video.path)[0]
    r = Project.restore(p.video.path, latest)
    assert r.persons[0].effect is None and (p.dir / "faces" / "0.jpg").read_bytes() == b"new"


def test_backups_keep_only_recent(tmp_path, monkeypatch):
    import blurface.project as proj
    monkeypatch.setattr(proj, "BACKUP_KEEP", 3)
    p = make(tmp_path)
    p.save()
    for _ in range(5):
        Project.backup(p.video.path)
    assert len(Project.backups(p.video.path)) == 3


HEART = {"type": "sticker", "value": "heart"}
SMILE = {"type": "sticker", "value": "smile"}


def test_split_then_piece_effect(tmp_path):
    p = make(tmp_path)
    assert p.split(0, 20) and p.split(0, 40) and not p.split(0, 20)
    assert p.pieces(0) == [(0, 20), (20, 40), (40, 100)]
    a, b = p.piece_at(0, 25)
    p.set_piece_effect(0, a, b, HEART)
    assert p.effect_for(0, 19) == p.default_effect and p.effect_for(0, 25) == HEART and p.effect_for(0, 40) == p.default_effect
    p.set_piece_effect(0, 20, 40, None)  # 조각을 다시 기본으로
    assert p.persons[0].segments == []


def test_move_split_resizes_pieces_and_clamps(tmp_path):
    p = make(tmp_path)
    p.split(0, 20)
    p.split(0, 40)
    p.set_piece_effect(0, 20, 40, HEART)
    assert p.move_split(0, 40, 50) == 50
    assert p.persons[0].segments == [{"start": 20, "end": 50, "effect": HEART}]
    assert p.move_split(0, 20, 70) == 49  # 옆 자른 곳(50)을 넘지 못함


def test_unsplit_merges_same_effect(tmp_path):
    p = make(tmp_path)
    p.add_segment(0, 10, 30, HEART)
    p.add_segment(0, 30, 50, HEART)
    p.unsplit(0, 30)
    assert p.persons[0].segments == [{"start": 10, "end": 50, "effect": HEART}]
    p.add_segment(0, 60, 70, SMILE)
    assert p.persons[0].splits == [10, 50, 60, 70]


def test_trim_and_restore_ends(tmp_path):
    p = make(tmp_path)
    p.remove_range(0, 0, 10)  # 시작을 10으로 줄임
    assert min(p.track_boxes(0)) == 10
    p.restore_range(0, 5, 10)  # 다시 5까지 늘림
    assert min(p.track_boxes(0)) == 5 and p.tracks[0].removed == [[0, 5]]


def test_old_project_names_and_segments_migrate(tmp_path):
    p = make(tmp_path)
    p.persons[0].name = "인물 0"
    p.persons[1].name = "철수"
    p.persons[0].segments = [{"start": 10, "end": 30, "effect": HEART}]
    p.save()
    d = json.loads((p.dir / "project.json").read_text())
    d["version"] = 3
    for v in d["persons"].values():
        v.pop("splits")
    (p.dir / "project.json").write_text(json.dumps(d))
    q = Project.load(p.video.path)
    assert q.persons[0].name == "인물 1" and q.persons[1].name == "철수"
    assert q.persons[0].splits == [10, 30]


def _two_pieces(tmp_path, gap_start=40, gap_end=48, x2=None):
    """한 사람(트랙 0, 1)이 gap_start~gap_end 사이에서 잠깐 끊긴 프로젝트 (10fps)."""
    p = make(tmp_path)
    x2 = 100 if x2 is None else x2
    p.auto[0] = AutoTrack(list(range(gap_start)), [[100, 100, 140, 140, 0.9]] * gap_start, ["auto"] * gap_start)
    p.auto[1] = AutoTrack(list(range(gap_end, 100)), [[x2, 100, x2 + 40, 140, 0.9]] * (100 - gap_end),
                          ["auto"] * (100 - gap_end))
    p.tracks[1].person = 0
    p.persons = {0: Person("A", [0, 1], [])}
    p._touch(0, 1)
    return p


def test_short_gap_is_bridged(tmp_path):
    p = _two_pieces(tmp_path, x2=120)
    assert p.person_frames(0) == list(range(100))
    tid, b, src = p.boxes_by_frame()[44][0]
    assert src == "interp" and b[0] == pytest.approx(100 + 20 * 5 / 9)  # 앞뒤 상자 사이를 보간


def test_long_gap_cut_removed_or_far_not_bridged(tmp_path):
    assert len(_two_pieces(tmp_path, 40, 60).person_frames(0)) < 100  # 1초 넘게 끊김
    p = _two_pieces(tmp_path)
    p.cuts = [45]  # 장면 전환
    p._touch()
    assert len(p.person_frames(0)) < 100
    p = _two_pieces(tmp_path)
    p.remove_range(0, 30, 40)  # 사람이 지운 구간과 맞닿은 틈
    p.remove_range(1, 48, 50)
    assert not set(range(30, 50)) & set(p.person_frames(0))
    assert len(_two_pieces(tmp_path, x2=400).person_frames(0)) < 100  # 다른 자리 (같은 사람이 아닐 수 있음)
