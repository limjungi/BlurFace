"""미리보기 소리: 영상 파일의 소리를 QMediaPlayer로 재생하고 화면 재생 위치에 맞춘다."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

DRIFT = 0.15  # 화면과 소리가 이만큼(초) 넘게 어긋나면 소리 위치를 다시 맞춤
CHECK_EVERY = 0.5  # 어긋남 확인 주기(초)


class AudioPlayer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.player.setVideoOutput(None)
        if hasattr(self.player, "setPitchCompensation"):
            self.player.setPitchCompensation(True)  # 0.5배·2배에서도 목소리 높이 유지
        self.enabled = False
        self._checked = 0.0

    def load(self, path: str | None, has_audio: bool = True):
        self.player.stop()
        self.enabled = bool(path) and has_audio
        self.player.setSource(QUrl.fromLocalFile(path) if self.enabled else QUrl())

    def play(self, t: float, rate: float = 1.0):
        if not self.enabled:
            return
        self.player.setPlaybackRate(rate)
        self.player.setPosition(int(t * 1000))
        self.player.play()
        self._checked = time.perf_counter()

    def pause(self):
        if self.enabled:
            self.player.pause()

    def seek(self, t: float):
        if self.enabled and self.playing:
            self.player.setPosition(int(t * 1000))
            self._checked = time.perf_counter()

    def set_rate(self, rate: float):
        if self.enabled:
            self.player.setPlaybackRate(rate)

    def sync(self, t: float):
        """화면 재생 위치 t(초)와 소리가 많이 어긋나면 맞춘다 (재생 중 주기적으로 호출)."""
        if not self.enabled or not self.playing:
            return
        now = time.perf_counter()
        if now - self._checked < CHECK_EVERY:
            return
        self._checked = now
        if abs(self.player.position() / 1000 - t) > DRIFT:
            self.player.setPosition(int(t * 1000))

    @property
    def playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def set_volume(self, v: float):
        self.output.setVolume(v)

    def set_muted(self, on: bool):
        self.output.setMuted(on)

    def stop(self):
        self.player.stop()
