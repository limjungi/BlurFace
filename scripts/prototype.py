"""0단계 시제품: 분석 → 모자이크 → 내보내기 전체 흐름을 돌리고 결과·시간을 출력한다.

사용: uv run python scripts/prototype.py test_videos/sample_fhd_cuts.mp4 [--debug]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blurface.analyze import analyze  # noqa: E402
from blurface.render import render  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("output/prototype"))
    ap.add_argument("--debug", action="store_true", help="트랙 번호·상자 표시")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for v in args.videos:
        a = analyze(v)
        dur = a.n_frames / a.fps
        n_auto = sum(1 for t in a.tracks.values() for b in t.values() if b[5] == "auto")
        n_interp = sum(1 for t in a.tracks.values() for b in t.values() if b[5] == "interp")
        suffix = "_debug" if args.debug else "_mosaic"
        out = args.out / f"{v.stem}{suffix}.mp4"
        t_render = render(v, a, out, debug=args.debug)
        print(f"\n## {v.name}  {a.width}x{a.height} {a.fps:.0f}fps {a.n_frames}프레임 ({dur:.1f}초)")
        print(f"- 컷: {len(a.cuts)}개 @ 프레임 {a.cuts}")
        print(f"- 트랙: {len(a.tracks)}개 / 상자: 검출 {n_auto}, 보간 {n_interp}")
        print(f"- 시간: 컷 감지 {a.timings['cuts']:.1f}s, 검출+추적 {a.timings['detect_track']:.1f}s, "
              f"내보내기 {t_render:.1f}s (영상 길이 {dur:.1f}s)")
        print(f"- 출력: {out}")
        summary = {tid: [min(b), max(b), len(b)] for tid, b in a.tracks.items()}
        (args.out / f"{v.stem}_tracks.json").write_text(json.dumps(
            {"cuts": a.cuts, "tracks": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
