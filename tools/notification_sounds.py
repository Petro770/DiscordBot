"""Non-blocking clipboard notifications using bundled WAV files."""
from pathlib import Path
from PyQt5.QtCore import QObject, QUrl
from PyQt5.QtMultimedia import QSoundEffect

from core.logging import log


class NotificationSounds(QObject):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.effects = {}
        directory = Path(__file__).resolve().parents[1] / "static" / "sounds"
        for name in ("started", "finished", "error"):
            effect = QSoundEffect(self)
            effect.setLoopCount(1)
            effect.setVolume(0.6)
            effect.statusChanged.connect(lambda name=name: self._check_status(name))
            self.effects[name] = effect
            effect.setSource(QUrl.fromLocalFile(str(directory / f"{name}.wav")))

    def _check_status(self, name):
        if self.effects[name].status() == QSoundEffect.Error:
            log.warning("Leikepöydän äänimerkkiä ei voitu ladata: %s.wav", name)

    def play(self, name):
        if not self.settings.value("clipboard/notificationSounds", True, type=bool):
            return
        # A quick result replaces the starting chime instead of overlapping it.
        for effect in self.effects.values():
            effect.stop()
        self.effects[name].play()
