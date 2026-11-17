"""원본과 결과 영상의 프레임 시각 비교 (가변 프레임레이트에서 영상·소리 어긋남 확인용).

사용: uv run python scripts/check_sync.py 원본.mp4 결과.mp4
"""

import subprocess
import sys


def frame_times(path: str) -> list[float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout
    vals = [x.strip(",") for x in out.split()]
    return [float(x) for x in vals if x and x != "N/A"]


def stream_duration(path: str, kind: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"{kind}:0", "-show_entries",
                          "stream=duration", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    try:
        return float(out.strip())
    except ValueError:
        return float("nan")


src, out = sys.argv[1], sys.argv[2]
a, b = frame_times(src), frame_times(out)
n = min(len(a), len(b))
diffs = [abs((b[i] - b[0]) - (a[i] - a[0])) for i in range(n)]
print(f"프레임 수: 원본 {len(a)}, 결과 {len(b)}")
print(f"프레임 시각 차이: 최대 {max(diffs) * 1000:.0f}ms, 마지막 프레임 {diffs[n - 1] * 1000:.0f}ms")
print(f"길이(영상/소리): 원본 {stream_duration(src, 'v'):.2f}/{stream_duration(src, 'a'):.2f}s, "
      f"결과 {stream_duration(out, 'v'):.2f}/{stream_duration(out, 'a'):.2f}s")
