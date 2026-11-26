"""Frame-by-frame preview of the last completed SoundCloud video."""
from dataclasses import replace
from io import BytesIO
import math
from pathlib import Path
from zipfile import BadZipFile

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QLabel, QSlider, QVBoxLayout, QWidget

from tools.soundcloud_preview_source import SoundCloudPreviewSource
from tools.soundcloud_video import _decode_envelopes, _envelope_arguments


class SoundCloudVideoPreview(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.source_menu = QComboBox()
        self.source_menu.setAccessibleName("Esikatselun lähde")
        layout.addWidget(self.source_menu)
        self.image = QLabel("Edellistä SoundCloud-videota ei ole saatavilla.")
        self.image.setWordWrap(True)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(260, 260)
        layout.addWidget(self.image, alignment=Qt.AlignmentFlag.AlignCenter)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName("Esikatselun aikaleima")
        self.slider.setEnabled(False)
        layout.addWidget(self.slider)
        self.timestamp = QLabel()
        layout.addWidget(self.timestamp, alignment=Qt.AlignmentFlag.AlignCenter)
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
        self.render_settings = {}
        self.analysis = QProcess(self)
        self.analysis.finished.connect(self._analysis_finished)
        self.analysis.errorOccurred.connect(self._analysis_error)
        self.analysis_key = None
        self.analyzed = None
        self.failed_key = None
        self.previous = None
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
        self.previous = source
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

    def set_render_settings(self, settings):
        self.render_settings = settings
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
            try:
                settings = replace(self.source.settings, **self.render_settings)
            except ValueError as error:
                self.image.setText(str(error))
                return
            source = self._wave_source(settings)
            if source is None:
                return
            image = source.frame(self.slider.value() / 1000, self.render_settings)
            image.thumbnail((260, 260))
            output = BytesIO()
            image.save(output, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(output.getvalue(), "PNG")
            self.image.setPixmap(pixmap)
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self.requested_ms = self.slider.value()
        self.process.start(self.ffmpeg, [
            "-nostdin", "-loglevel", "error", "-ss", f"{self.requested_ms / 1000:.3f}",
            "-i", self.path, "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=260:260",
            "-f", "image2pipe", "-c:v", "mjpeg", "-threads", "1", "pipe:1",
        ])

    @staticmethod
    def _wave_key(settings):
        return settings.bands, min(15, settings.fps * 0.3)

    def _wave_source(self, settings):
        if self.source is not self.previous:
            if self.source.settings.bands == settings.bands:
                return self.source
            return SoundCloudPreviewSource.example(settings)

        key = self._wave_key(settings)
        if key == self._wave_key(self.source.settings):
            return self.source
        if self.analyzed is not None and self.analyzed[0] == key:
            return replace(self.source, envelopes=self.analyzed[1])
        if self.failed_key == key:
            self.image.setText("Aaltomuodon analyysi epäonnistui.")
            return None
        if self.analysis.state() == QProcess.ProcessState.NotRunning:
            self.analysis_key = key
            self.image.setText("Analysoidaan videon ääntä…")
            self.analysis.start(self.ffmpeg, _envelope_arguments(self.path, settings))
        return None

    def _analysis_finished(self, exit_code, exit_status):
        data = bytes(self.analysis.readAllStandardOutput())
        self.analysis.readAllStandardError()
        key, self.analysis_key = self.analysis_key, None
        if key is None:
            return
        try:
            if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit or not data:
                raise ValueError("Aaltomuodon analyysi epäonnistui.")
            self.analyzed = key, _decode_envelopes(data, key[0])
        except ValueError:
            self.failed_key = key
        self.timer.start()

    def _analysis_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.failed_key, self.analysis_key = self.analysis_key, None
            self.timer.start()

    def _finished(self, exit_code, exit_status):
        data = bytes(self.process.readAllStandardOutput())
        self.process.readAllStandardError()
        if self.requested_ms is None:
            return
        if self.requested_ms != self.slider.value():
            self.timer.start()
            return
        image = QPixmap()
        if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit and image.loadFromData(data, "JPEG"):
            self.image.setPixmap(image)
        else:
            self.image.setText("Ruutua ei voitu lukea edellisestä videosta.")

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.image.setText("Esikatselua ei voitu avata. Renderöi uusi SoundCloud-video.")

    def stop(self):
        self.timer.stop()
        self.requested_ms = None
        self.analysis_key = None
        for process in (self.process, self.analysis):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(500)
