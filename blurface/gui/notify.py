"""맥 알림 센터 알림."""

from __future__ import annotations

import subprocess
import sys


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, text: str, sound: bool = True) -> bool:
    """알림 센터에 알림을 띄운다. 맥이 아니거나 실패하면 False."""
    if sys.platform != "darwin":
        return False
    script = f"display notification {_quote(text)} with title {_quote(title)}"
    if sound:
        script += ' sound name "Glass"'
    try:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
