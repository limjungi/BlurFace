"""영상 분석 (디코딩 한 번): 프레임마다 컷 특징값·얼굴 검출·(일부 프레임) 얼굴 특징값 →
끝난 뒤 컷 판단 → 컷 단위 추적 → 빈 구간 보간·떨림 보정 → 인물 묶기 → 인물 얼굴 목록 이미지.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from .cuts import differences, find_cuts, signature
from .detect.scrfd import SCRFD
from .embed import MODELS, ArcFace
from .persons import cluster_tracks, contact_sheet, face_crop, grab_frames
from .project import Person, Project, Track, effect_label
from .track import Tracker
from .video import iter_frames, probe

ANALYSIS_SIDE = 1920  # 4K는 FHD로 줄여서 분석
EMBED_PER_SEC = 5  # 초당 얼굴 특징값 추출 횟수
MIN_EMBED_FACE = 24  # 이보다 작은 얼굴(분석 해상도 px)은 특징값이 부정확해 건너뜀
EDGE_EVERY = 2  # 가장자리 얼굴 검출 간격(프레임). 사이는 추적이 이어 줌


def fill_and_smooth(obs: dict[int, tuple], max_gap: int, extend: int, lo: int, hi: int, window: int = 5):
    """관측 사이 빈 프레임 보간, 앞뒤 연장(같은 컷 안에서만), 이동 평균 떨림 보정.

    반환: {프레임: (x1, y1, x2, y2, score, source)}
    """
    frames = sorted(obs)
    out: dict[int, tuple] = {f: (*obs[f][:5], "auto") for f in frames}
    for a, b in zip(frames, frames[1:]):
        if 1 < b - a <= max_gap:
            pa, pb = np.array(obs[a][:4]), np.array(obs[b][:4])
            for f in range(a + 1, b):
                t = (f - a) / (b - a)
                out[f] = (*(pa + (pb - pa) * t), min(obs[a][4], obs[b][4]), "interp")
    first, last = frames[0], frames[-1]
    for f in range(max(lo, first - extend), first):
        out[f] = (*obs[first][:5], "interp")
    for f in range(last + 1, min(hi, last + extend + 1)):
        out[f] = (*obs[last][:5], "interp")

    keys = sorted(out)
    arr = np.array([out[f][:4] for f in keys], dtype=np.float64)
    half = window // 2
    smoothed = arr.copy()
    for i in range(len(keys)):
        j0 = j1 = i
        while j0 > max(0, i - half) and keys[j0 - 1] == keys[j0] - 1:
            j0 -= 1
        while j1 < min(len(keys) - 1, i + half) and keys[j1 + 1] == keys[j1] + 1:
            j1 += 1
        smoothed[i] = arr[j0:j1 + 1].mean(axis=0)
    return {f: (*smoothed[i], out[f][4], out[f][5]) for i, f in enumerate(keys)}


def analyze(video: str | Path, progress=None, log=print, cancel=None) -> Project:
    info = probe(video)
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    detector = SCRFD(str(MODELS / "buffalo_l/det_10g.onnx"), 640, score_thresh=0.3, edge_pad=0.2)
    embedder = ArcFace()
    embed_every = max(1, round(info.fps / EMBED_PER_SEC))

    diffs_sigs = []
    all_dets: list[np.ndarray] = []
    embs: dict[tuple[int, int], np.ndarray] = {}
    prev_sig = None
    n = 0
    pts_list: list[float] = []
    for i, pts, img in iter_frames(info, ANALYSIS_SIDE):
        if cancel and cancel():
            raise InterruptedError("분석 취소됨")
        pts_list.append(pts)
        sig = signature(img)
        diffs_sigs.append(0.0 if prev_sig is None else differences([prev_sig, sig])[1])
        prev_sig = sig

        d = detector.detect(img, edge=i % EDGE_EVERY == 0)
        if i % embed_every == 0:
            for j, x in enumerate(d):
                if x[4] >= 0.5 and x[2] - x[0] >= MIN_EMBED_FACE:
                    embs[(i, j)] = embedder.embed(img, x[5:15])
        kx, ky = info.width / img.shape[1], info.height / img.shape[0]
        if len(d):
            d[:, [0, 2]] *= kx
            d[:, [1, 3]] *= ky
        all_dets.append(d[:, :5])
        n = i + 1
        if progress and i % 30 == 0:
            progress(i, info.n_frames)
    timings["decode_detect"] = time.perf_counter() - t0

    t1 = time.perf_counter()
    cuts = find_cuts(np.array(diffs_sigs))
    bounds = [0, *cuts, n]
    max_lost = max(5, round(info.fps * 0.5))
    raw = []
    next_id = 0
    for lo, hi in zip(bounds, bounds[1:]):
        tracker = Tracker(next_id=next_id, max_lost=max_lost)
        for f in range(lo, hi):
            d = all_dets[f]
            tracker.update(f, np.hstack([d, np.arange(len(d))[:, None]]) if len(d) else d)
        raw += [(t, lo, hi) for t in tracker.close()]
        next_id = tracker.next_id

    tracks: dict[int, Track] = {}
    track_embs: dict[int, np.ndarray | None] = {}
    track_frames: dict[int, set[int]] = {}
    for t, lo, hi in raw:
        scores = [o[4] for o in t.observations.values()]
        if len(scores) < 3 and max(scores) < 0.7:  # 짧고 점수 낮으면 오검출
            continue
        filled = fill_and_smooth(t.observations, max_gap=max_lost, extend=2, lo=lo, hi=hi)
        tid = len(tracks)
        frames = sorted(filled)
        tracks[tid] = Track(-1, frames, [list(filled[f][:5]) for f in frames], [filled[f][5] for f in frames])
        vecs = [embs[(f, j)] for f, j in t.refs.items() if (f, j) in embs]
        if vecs:
            v = np.mean(vecs, axis=0)
            track_embs[tid] = v / (np.linalg.norm(v) + 1e-9)
        else:
            track_embs[tid] = None
        track_frames[tid] = set(frames)

    person_of = cluster_tracks(track_embs, track_frames)
    persons: dict[int, Person] = {}
    for tid, pid in sorted(person_of.items()):
        tracks[tid].person = pid
        persons.setdefault(pid, Person(name=f"인물 {pid}", tracks=[], thumb=[]))
        persons[pid].tracks.append(tid)
    for pid, p in persons.items():
        # 대표 얼굴: 점수 x 크기가 가장 큰 자동 검출 상자
        best = max(((f, b) for tid in p.tracks for f, b, s in
                    zip(tracks[tid].frames, tracks[tid].boxes, tracks[tid].sources) if s == "auto"),
                   key=lambda fb: fb[1][4] * (fb[1][2] - fb[1][0]), default=None)
        if best:
            p.thumb = [best[0], *best[1][:4]]
    timings["track_cluster"] = time.perf_counter() - t1

    t_first = pts_list[0] if pts_list else 0.0  # 영상 시작을 0초로
    project = Project(info, n, cuts, tracks, persons, timings=timings, pts=[t - t_first for t in pts_list])
    project.timings["total_analyze"] = time.perf_counter() - t0
    project.save()
    write_person_sheet(project)
    log(f"분석 완료: {n}프레임, 컷 {len(cuts)}개, 트랙 {len(tracks)}개, 인물 {len(persons)}명 "
        f"({project.timings['total_analyze']:.1f}초)")
    return project


def write_person_sheet(project: Project) -> Path:
    """인물별 대표 얼굴을 한 장으로 모은 이미지 (persons.jpg)."""
    thumbs = {pid: p.thumb for pid, p in project.persons.items() if p.thumb}
    frames = grab_frames(project.video, {int(t[0]) for t in thumbs.values()})
    faces_dir = project.dir / "faces"
    faces_dir.mkdir(parents=True, exist_ok=True)
    crops = []
    for pid, p in sorted(project.persons.items()):
        if pid not in thumbs:
            continue
        crop = face_crop(frames[int(p.thumb[0])], p.thumb[1:])
        cv2.imwrite(str(faces_dir / f"{pid}.jpg"), crop)
        secs = sum(len(project.tracks[t].frames) for t in p.tracks) / project.video.fps
        title = f"#{pid}  {secs:.1f}s" + ("  ?" if project.needs_review(pid) else "")
        crops.append((title, effect_label(project.effect_for(pid)), crop))
    path = project.dir / "persons.jpg"
    if crops:
        cv2.imwrite(str(path), contact_sheet(crops))
    return path
