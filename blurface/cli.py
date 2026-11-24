"""blurface 명령어.

  blurface gui [영상.mp4]                     화면으로 열기
  blurface run 영상.mp4                       분석(처음 한 번) + 모자이크 영상 만들기
  blurface analyze 영상.mp4                   분석만 (인물 목록 이미지 생성)
  blurface persons 영상.mp4                   인물 목록과 현재 효과 보기
  blurface render 영상.mp4 [옵션]             저장된 분석으로 영상 만들기

효과 지정 (run/render 공통)
  --effect blur:40                            모든 인물 기본 효과
  --person 2=sticker:smile --person 1=none    인물별 효과 (설정은 프로젝트에 저장됨)
  --person-at 2@12-20=sticker:heart           인물 2만 12~20초 동안 다른 효과 (시각: 초, 1:05, 1:05.5)
  --clear-at 2                                인물 2의 구간 효과 모두 지우기
  효과: mosaic[:블록수] blur[:강도] solid[:#색] sticker[:smile|heart] image:파일.png|gif none
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .project import Project, effect_label, parse_effect


def _progress(label: str):
    start = time.perf_counter()

    def cb(i: int, total: int):
        pct = f"{i / total * 100:5.1f}%" if total else f"{i}프레임"
        print(f"\r{label} {pct}  ({time.perf_counter() - start:.0f}초)", end="", file=sys.stderr, flush=True)
    return cb


def _load_or_analyze(video: Path, reanalyze: bool = False) -> Project:
    from .analyze import analyze

    p = None if reanalyze else Project.load(video)
    if p is None:
        p = analyze(video, progress=_progress("분석 중"))
        print(file=sys.stderr)
    return p


def parse_time(text: str) -> float:
    parts = text.strip().split(":")
    secs = 0.0
    for part in parts:
        secs = secs * 60 + float(part)
    return secs


def _person_id(p: Project, text: str) -> int:
    num = int(text.strip().lstrip("#P"))  # 화면과 같이 1번부터
    if num - 1 not in p.persons:
        raise SystemExit(f"인물 #{num} 없음 (blurface persons 로 목록 확인)")
    return num - 1


def _apply_effect_options(p: Project, args) -> bool:
    changed = False
    for spec in getattr(args, "clear_at", None) or []:
        person = p.persons[_person_id(p, spec)]
        person.segments, person.splits = [], []
        changed = True
    if getattr(args, "effect", None):
        p.default_effect = parse_effect(args.effect)
        changed = True
    for spec in getattr(args, "person", None) or []:
        pid_s, _, eff = spec.partition("=")
        p.persons[_person_id(p, pid_s)].effect = parse_effect(eff)
        changed = True
    for spec in getattr(args, "person_at", None) or []:
        head, _, eff = spec.partition("=")
        pid_s, _, span = head.partition("@")
        a, _, b = span.partition("-")
        if not a or not b:
            raise SystemExit(f"구간 형식 오류: {spec} (예: 2@12-20=sticker:heart)")
        p.add_segment(_person_id(p, pid_s), p.frame_at(parse_time(a)), p.frame_at(parse_time(b)), parse_effect(eff))
        changed = True
    if changed:
        p.save()
    return changed


def _print_persons(p: Project):
    print(f"인물 {len(p.persons)}명  (기본 효과: {effect_label(p.default_effect)})")
    for pid, person in sorted(p.persons.items()):
        secs = len(p.person_frames(pid)) / p.video.fps
        mark = "" if person.effect else " (기본)"
        warn = "  ⚠ 확인 필요" if p.needs_review(pid) else ""
        print(f"  #{pid + 1:<3} {secs:6.1f}초  트랙 {len(person.tracks):<3} {effect_label(p.effect_for(pid))}{mark}{warn}")
        for seg in person.segments:
            print(f"        {p.time_of(seg['start']):6.2f}~{p.time_of(seg['end']):6.2f}초  {effect_label(seg['effect'])}")
    print(f"얼굴 목록 이미지: {p.dir / 'persons.jpg'}")


def _render(p: Project, args):
    from .analyze import write_person_sheet
    from .render import render

    out = Path(args.output) if args.output else Path(p.video.path).with_name(Path(p.video.path).stem + "_mosaic.mp4")
    write_person_sheet(p)
    secs = render(p, out, debug=args.debug, progress=_progress("내보내는 중"))
    print(file=sys.stderr)
    print(f"완료: {out}  ({secs:.1f}초)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="blurface", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def effect_opts(sp):
        sp.add_argument("--effect", help="모든 인물 기본 효과")
        sp.add_argument("--person", action="append", metavar="번호=효과", help="인물별 효과 (여러 번 사용 가능)")
        sp.add_argument("--person-at", action="append", metavar="번호@시작-끝=효과", help="인물별 구간 효과")
        sp.add_argument("--clear-at", action="append", metavar="번호", help="인물의 구간 효과 지우기")
        sp.add_argument("-o", "--output", help="출력 파일 (기본: 원본이름_mosaic.mp4)")
        sp.add_argument("--debug", action="store_true", help="상자와 인물 번호 표시")

    sp = sub.add_parser("gui", help="화면으로 열기")
    sp.add_argument("video", type=Path, nargs="?")
    sp = sub.add_parser("run", help="분석 + 영상 만들기")
    sp.add_argument("video", type=Path)
    sp.add_argument("--reanalyze", action="store_true", help="저장된 분석 무시하고 다시 분석")
    effect_opts(sp)
    sp = sub.add_parser("analyze", help="분석만")
    sp.add_argument("video", type=Path)
    sp = sub.add_parser("persons", help="인물 목록")
    sp.add_argument("video", type=Path)
    sp = sub.add_parser("render", help="저장된 분석으로 영상 만들기")
    sp.add_argument("video", type=Path)
    effect_opts(sp)

    args = ap.parse_args(argv)
    if args.cmd == "gui":
        from .gui.app import main as gui_main

        raise SystemExit(gui_main(["blurface"] + ([str(args.video)] if args.video else [])))
    if not args.video.exists():
        raise SystemExit(f"파일 없음: {args.video}")

    if args.cmd == "analyze":
        p = _load_or_analyze(args.video, reanalyze=True)
        _print_persons(p)
    elif args.cmd == "persons":
        p = Project.load(args.video)
        if p is None:
            raise SystemExit("분석 결과 없음. 먼저 blurface analyze 실행")
        _print_persons(p)
    else:
        if args.cmd == "render" and Project.load(args.video) is None:
            raise SystemExit("분석 결과 없음. 먼저 blurface analyze 실행")
        p = _load_or_analyze(args.video, reanalyze=getattr(args, "reanalyze", False))
        _apply_effect_options(p, args)
        _print_persons(p)
        _render(p, args)


if __name__ == "__main__":
    main()
