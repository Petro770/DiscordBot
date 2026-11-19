"""Frame-by-frame preview of the last completed SoundCloud video."""
from io import BytesIO
import math
from pathlib import Path
from zipfile import BadZipFile

from PyQt5.QtCore import QProcess, Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QComboBox, QLabel, QSlider, QVBoxLayout, QWidget

from tools.soundcloud_preview_source import SoundCloudPreviewSource


class SoundCloudVideoPreview(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.source_menu = QComboBox()
        self.source_menu.setAccessibleName("Esikatselun lähde")
        layout.addWidget(self.source_menu)
        self.image = QLabel("Edellistä SoundCloud-videota ei ole saatavilla.")
        self.image.setWordWrap(True)
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setFixedSize(260, 260)
        layout.addWidget(self.image, alignment=Qt.AlignCenter)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setAccessibleName("Esikatselun aikaleima")
        self.slider.setEnabled(False)
        layout.addWidget(self.slider)
        self.timestamp = QLabel()
        layout.addWidget(self.timestamp, alignment=Qt.AlignCenter)
        layout.addStretch()

        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._read_frame)
        self.slider.valueChanged.connect(self._seek)
        self.requested_ms = None
        self.floor_settings = {}
        self.source = None
        self.sources = []
        self._add_previous(settings)
        example = SoundCloudPreviewSource.example()
        self.sources.append((example, example.duration, example.settings.fps))
        self.source_menu.addItem("Beatfloor-malli · 120 BPM")
        self.source_menu.currentIndexChanged.connect(self._select_source)
        if self.sources[0][0] is None:
            self.source_menu.setCurrentIndex(1)
        else:
            self._select_source(0)

    def _add_previous(self, settings):
        try:
            path, ffmpeg, duration, fps = settings.value("clipboard/lastSoundCloudVideo", [])
            duration, fps = float(duration), int(fps)
            if not math.isfinite(duration) or duration <= 0 or fps <= 0:
                return
            if not Path(path).is_file() or not ffmpeg:
                return
        except (TypeError, ValueError, OSError):
            return
        self.path, self.ffmpeg = path, ffmpeg
        source = None
        try:
            source = SoundCloudPreviewSource.from_archive(Path(path).with_name("soundcloud-preview.zip"))
        except (OSError, ValueError, TypeError, KeyError, BadZipFile):
            pass
        if source is not None:
            duration, fps = source.duration, source.settings.fps
        self.sources.append((source, duration, fps))
        self.source_menu.addItem("Edellinen video" if source is not None else "Edellinen video · valmis MP4")

    def _select_source(self, index):
        self.stop()
        self.source, duration, fps = self.sources[index]
        self.duration_ms = round(duration * 1000)
        self.slider.setRange(0, max(0, self.duration_ms - math.ceil(1000 / fps)))
        self.slider.setSingleStep(100)
        self.slider.setPageStep(1000)
        self.slider.setEnabled(self.slider.maximum() > 0)
        self.slider.setValue(0 if self.source is None else min(1000, self.slider.maximum()))
        self._seek(self.slider.value())

    def set_floor_settings(self, settings):
        self.floor_settings = settings
        if self.source is not None:
            self.timer.start()

    @staticmethod
    def _time(milliseconds):
        seconds, tenths = divmod(milliseconds // 100, 10)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes}:{seconds:02d}.{tenths}"

    def _seek(self, milliseconds):
        self.timestamp.setText(f"{self._time(milliseconds)} / {self._time(self.duration_ms)}")
        self.timer.start()

    def _read_frame(self):
        if self.source is not None:
            image = self.source.frame(self.slider.value() / 1000, self.floor_settings)
            image.thumbnail((260, 260))
            output = BytesIO()
            image.save(output, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(output.getvalue(), "PNG")
            self.image.setPixmap(pixmap)
            return
        if self.process.state() != QProcess.NotRunning:
            return
        self.requested_ms = self.slider.value()
        self.process.start(self.ffmpeg, [
            "-nostdin", "-loglevel", "error", "-ss", f"{self.requested_ms / 1000:.3f}",
            "-i", self.path, "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=260:260",
            "-f", "image2pipe", "-c:v", "mjpeg", "-threads", "1", "pipe:1",
        ])

    def _finished(self, exit_code, exit_status):
        data = bytes(self.process.readAllStandardOutput())
        self.process.readAllStandardError()
        if self.requested_ms is None:
            return
        if self.requested_ms != self.slider.value():
            self.timer.start()
            return
        image = QPixmap()
        if exit_code == 0 and exit_status == QProcess.NormalExit and image.loadFromData(data, "JPEG"):
            self.image.setPixmap(image)
        else:
            self.image.setText("Ruutua ei voitu lukea edellisestä videosta.")

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self.image.setText("Esikatselua ei voitu avata. Renderöi uusi SoundCloud-video.")

    def stop(self):
        self.timer.stop()
        self.requested_ms = None
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(500)
