import numpy as np
import pytest

from blurface.analyze import fill_and_smooth
from blurface.cuts import find_cuts
from blurface.effects import apply, expand_box
from blurface.persons import cluster_tracks
from blurface.project import AutoTrack, Person, Project, Track, parse_effect
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
    p = Project(info, 10, [5], {0: Track(0, auto=0)}, {0: Person("인물 0", [0], [1, 1, 2, 3, 4], parse_effect("blur:20"))},
                auto={0: AutoTrack([1, 2], [[1, 2, 3, 4, 0.9], [2, 3, 4, 5, 0.8]], ["auto", "interp"])})
    p.set_key(0, 2, [5, 5, 9, 9])
    p.remove_range(0, 8, 9)
    p.save()
    q = Project.load(video)
    assert q.cuts == [5]
    assert q.auto[0].sources == ["auto", "interp"]
    assert q.tracks[0].keys == {2: [5, 5, 9, 9]} and q.tracks[0].removed == [[8, 9]]
    assert q.track_boxes(0)[2] == ([5, 5, 9, 9, 1.0], "manual")
    assert q.persons[0].effect == {"type": "blur", "value": 20.0}
    assert q.effect_for(0)["type"] == "blur"


def _project(tmp_path, n=100):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    info = VideoInfo(str(video), 1920, 1080, 10.0, "10/1", n, 0, False, "h264", 0, {}, True)
    return Project(info, n, [], {}, {0: Person("인물 0", [], [], parse_effect("sticker:smile"))},
                   pts=[i / 10 for i in range(n)])


def test_segment_overrides_person_effect_only_inside_range(tmp_path):
    p = _project(tmp_path)
    p.add_segment(0, p.frame_at(2.0), p.frame_at(4.0), parse_effect("sticker:heart"))
    assert p.effect_for(0, 19)["value"] == "smile"
    assert p.effect_for(0, 20)["value"] == "heart"
    assert p.effect_for(0, 39)["value"] == "heart"
    assert p.effect_for(0, 40)["value"] == "smile"
    assert p.effect_for(0)["value"] == "smile"  # 시점 없이 물으면 인물 기본 효과


def test_later_segment_wins_and_segments_survive_save(tmp_path):
    p = _project(tmp_path)
    p.add_segment(0, 10, 50, parse_effect("blur"))
    p.add_segment(0, 30, 40, parse_effect("none"))
    p.add_segment(0, 90, 500, parse_effect("mosaic"))  # 영상 끝을 넘으면 잘림
    p.save()
    q = Project.load(p.video.path)
    assert q.effect_for(0, 20)["type"] == "blur"
    assert q.effect_for(0, 35)["type"] == "none"
    assert q.persons[0].segments[-1]["end"] == 100


def test_parse_time_formats():
    from blurface.cli import parse_time
    assert parse_time("12") == 12
    assert parse_time("1:05.5") == 65.5
    assert parse_time("1:00:00") == 3600


def test_sticker_gaps_are_blurred_not_original():
    rng = np.random.default_rng(1)
    img = (rng.random((300, 300, 3)) * 255).astype(np.uint8)
    before = img.copy()
    box = (100, 100, 200, 200)
    apply(img, box, parse_effect("sticker:heart"))
    # 하트 아래쪽 모서리는 투명한 곳 → 원본 그대로가 아니라 흐려져 있어야 함
    corner = (slice(185, 199), slice(101, 115))
    assert not np.array_equal(img[corner], before[corner])
    assert img[corner].std() < before[corner].std() / 2


def _noise(dtype=np.uint8, hi=255):
    return (np.random.default_rng(2).random((300, 300, 3)) * hi).astype(dtype)


@pytest.mark.parametrize("dtype,hi", [(np.uint8, 255), (np.uint16, 65535)])
def test_ellipse_keeps_corners_and_covers_center(dtype, hi):
    img = _noise(dtype, hi)
    before = img.copy()
    apply(img, [100, 100, 200, 200], parse_effect("solid:#ff0000,shape=ellipse"))
    assert np.array_equal(img[101, 101], before[101, 101])  # 모서리는 원본
    assert img[150, 150].tolist() == [0, 0, hi]  # 가운데는 빨강(BGR)


def test_feather_fades_outside_but_fully_covers_box():
    img = _noise()
    before = img.copy()
    apply(img, [100, 100, 200, 200], parse_effect("solid:#ff0000,feather=20"))
    red = (img == [0, 0, 255]).all(axis=2)
    assert red[100:200, 100:200].all()  # 원래 영역은 빠짐없이 완전히 덮임
    edge = img[150, 210].astype(int)  # 바깥 20px: 반쯤 섞임
    assert not np.array_equal(edge, before[150, 210]) and not red[150, 210]
    assert np.array_equal(img[150, 250], before[150, 250])  # 2f(=40px) 밖은 원본


def test_scale_option_grows_cover_area():
    from blurface.effects import cover_box
    a = cover_box([100, 100, 200, 200])
    b = cover_box([100, 100, 200, 200], {"scale": 150})
    assert (b[2] - b[0]) == pytest.approx((a[2] - a[0]) * 1.5)
    assert (b[0] + b[2]) / 2 == pytest.approx((a[0] + a[2]) / 2)


def test_box_outside_frame_keeps_shape():
    img = np.zeros((100, 100, 3), np.uint8)
    apply(img, [-50, 20, 50, 80], parse_effect("solid:#ffffff,shape=ellipse"))
    assert img[50, 0].any()  # 화면 밖으로 나간 타원도 안쪽 부분은 칠해짐
    assert not img[21, 49].any()  # 타원 바깥 모서리


def test_parse_effect_options():
    e = parse_effect("blur:40,shape=rounded,feather=15,scale=130")
    assert e == {"type": "blur", "value": 40.0, "shape": "rounded", "feather": 15.0, "scale": 130.0}
    assert parse_effect("mosaic,scale=999")["scale"] == 300
    with pytest.raises(ValueError):
        parse_effect("blur,shape=star")
    from blurface.project import effect_label
    assert parse_effect(effect_label(e)) == e


def test_image_has_no_blur_underneath_by_default(tmp_path):
    import cv2
    png = tmp_path / "s.png"
    st = np.zeros((100, 100, 4), np.uint8)
    cv2.circle(st, (50, 50), 30, (0, 255, 0, 255), -1)  # 가운데 원만 보이고 나머지는 투명
    cv2.imwrite(str(png), st)
    from blurface.effects import load_image
    assert load_image(str(png)).shape[:2] == (61, 61)  # 투명 여백 잘림
    img = _noise()
    before = img.copy()
    apply(img, [100, 100, 200, 200], parse_effect(f"image:{png}"))
    corner = (slice(101, 106), slice(101, 106))  # 원 바깥(투명) → 원본 그대로
    assert np.array_equal(img[corner], before[corner])
    img2 = before.copy()
    apply(img2, [100, 100, 200, 200], parse_effect(f"image:{png},under=1"))
    assert not np.array_equal(img2[corner], before[corner])  # 옵션을 켜면 흐림
