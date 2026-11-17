import numpy as np
import pytest

from blurface.analyze import fill_and_smooth
from blurface.cuts import find_cuts
from blurface.effects import apply, expand_box
from blurface.persons import cluster_tracks
from blurface.project import Person, Project, Track, parse_effect
from blurface.track import Tracker
from blurface.video import VideoInfo


def det(x, y, s=0.9, size=50):
    return [x, y, x + size, y + size, s]


def test_tracker_follows_moving_face_and_keeps_id():
    tr = Tracker(max_lost=5)
    for f in range(20):
        tr.update(f, np.array([det(100 + f * 5, 100)]))
    tracks = tr.close()
    assert len(tracks) == 1
    assert len(tracks[0].observations) == 20


def test_tracker_uses_low_score_detection_to_continue_track():
    tr = Tracker(max_lost=5)
    tr.update(0, np.array([det(100, 100, 0.9)]))
    tr.update(1, np.array([det(102, 100, 0.4)]))  # 흐려져서 점수 낮음
    tracks = tr.close()
    assert len(tracks) == 1 and len(tracks[0].observations) == 2


def test_tracker_does_not_start_track_from_low_score():
    tr = Tracker()
    tr.update(0, np.array([det(100, 100, 0.4)]))
    assert tr.close() == []


def test_fill_interpolates_gap_and_extends_within_shot():
    obs = {10: (0, 0, 10, 10, 0.9), 14: (40, 0, 50, 10, 0.9)}
    out = fill_and_smooth(obs, max_gap=10, extend=2, lo=9, hi=100, window=1)
    assert out[12][0] == pytest.approx(20)
    assert out[12][5] == "interp"
    assert 9 in out and 8 not in out  # 컷 경계(lo=9) 앞으로는 늘리지 않음
    assert 16 in out and 17 not in out


def test_find_cuts_ignores_sustained_motion():
    d = np.full(100, 0.01)
    d[30] = 0.8  # 진짜 컷: 한 프레임만 튐
    d[60:70] = 0.5  # 빠른 움직임: 계속 큼
    assert find_cuts(d) == [30]


def test_cluster_merges_similar_and_respects_cannot_link():
    a = np.array([1.0, 0, 0])
    b = np.array([0, 1.0, 0])
    embs = {0: a, 1: b, 2: a, 3: a}
    frames = {0: {1, 2}, 1: {1, 2}, 2: {10, 11}, 3: {10}}  # 2와 3은 같은 프레임에 함께 나옴
    person = cluster_tracks(embs, frames)
    assert person[0] == person[2] or person[0] == person[3]
    assert person[2] != person[3]
    assert person[0] != person[1]


@pytest.mark.parametrize("dtype,hi", [(np.uint8, 255), (np.uint16, 65535)])
@pytest.mark.parametrize("spec", ["mosaic", "blur", "solid:#ff0000", "sticker:smile", "sticker:heart", "none"])
def test_effects_run_on_8_and_16_bit(dtype, hi, spec):
    rng = np.random.default_rng(0)
    img = (rng.random((200, 300, 3)) * hi).astype(dtype)
    before = img.copy()
    box = expand_box([100, 60, 160, 120], 300, 200)
    apply(img, box, parse_effect(spec))
    assert img.dtype == dtype
    outside = np.ones(img.shape[:2], bool)
    outside[:, 80:220] = False  # 스티커는 상자보다 조금 넓을 수 있음
    assert np.array_equal(img[outside], before[outside])
    changed = not np.array_equal(img, before)
    assert changed == (spec != "none")


def test_effect_at_frame_edge_does_not_crash():
    img = np.zeros((100, 100, 3), np.uint8)
    for spec in ["mosaic", "blur", "sticker:smile"]:
        apply(img, expand_box([-20, -20, 30, 30], 100, 100), parse_effect(spec))
        apply(img, expand_box([80, 80, 130, 130], 100, 100), parse_effect(spec))


def test_parse_effect_rejects_unknown_and_missing_image():
    with pytest.raises(ValueError):
        parse_effect("pixelate")
    with pytest.raises(ValueError):
        parse_effect("image:/없는/파일.png")


def test_project_save_load_roundtrip(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    info = VideoInfo(str(video), 1920, 1080, 30.0, "30/1", 10, 0, False, "h264", 0, {}, True)
    p = Project(info, 10, [5], {0: Track(0, [1, 2], [[1, 2, 3, 4, 0.9], [2, 3, 4, 5, 0.8]], ["auto", "interp"])},
                {0: Person("인물 0", [0], [1, 1, 2, 3, 4], parse_effect("blur:20"))})
    p.save()
    q = Project.load(video)
    assert q.cuts == [5]
    assert q.tracks[0].sources == ["auto", "interp"]
    assert q.persons[0].effect == {"type": "blur", "value": 20.0}
    assert q.effect_for(0)["type"] == "blur"
