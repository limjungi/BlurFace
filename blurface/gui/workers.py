"""오래 걸리는 작업(분석, 내보내기)을 화면이 멈추지 않게 별도 스레드에서 실행."""

from __future__ import annotations

import copy
import traceback

from PySide6.QtCore import QThread, Signal

from ..project import Project


class _Worker(QThread):
    progress = Signal(int, int)  # 현재, 전체
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _is_cancelled(self) -> bool:
        return self._cancel

    def run(self):
        try:
            self.work()
        except InterruptedError:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 - 화면에 오류를 보여주기 위함
            traceback.print_exc()
            self.failed.emit(str(e))

    def work(self):  # pragma: no cover
        raise NotImplementedError


class AnalyzeWorker(_Worker):
    done = Signal(object)  # Project

    def __init__(self, video: str):
        super().__init__()
        self.video = video

    def work(self):
        from ..analyze import analyze

        p = analyze(self.video, progress=self.progress.emit, log=lambda *_: None, cancel=self._is_cancelled)
        self.done.emit(p)


class ExportWorker(_Worker):
    done = Signal(str, float)  # 출력 경로, 걸린 시간

    def __init__(self, project: Project, out: str, opts=None):
        super().__init__()
        self.project = copy.deepcopy(project)  # 내보내는 동안 화면에서 바꿔도 영향 없게
        self.out = out
        self.opts = opts

    def work(self):
        from ..render import render

        secs = render(self.project, self.out, progress=self.progress.emit, cancel=self._is_cancelled, opts=self.opts)
        self.done.emit(self.out, secs)
