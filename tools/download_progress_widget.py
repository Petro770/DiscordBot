"""Live phase timings for one clipboard download."""
from base64 import b64decode
from time import monotonic
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QPlainTextEdit, QCheckBox

STAGES = {
    "starting": "Käynnistys", "resolve": "Linkin selvitys", "prepare": "Latauksen valmistelu",
    "download": "Verkkolataus", "audio": "Äänen muunnos", "artwork": "Kansikuva",
    "analysis": "Taajuuskaistojen analyysi", "render": "Videon muodostus",
    "finalize": "MP4:n viimeistely", "compress": "Kokorajan pakkaus", "save": "Tallennus",
}


class DownloadProgressWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.phase = QLabel("Ei latausta käynnissä")
        self.phase.setWordWrap(True)
        self.timing = QLabel()
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setMaximumBlockCount(100)
        self.history.setMaximumHeight(100)
        for widget in (self.phase, self.timing, self.bar, self.history):
            layout.addWidget(widget)
        self.preview_toggle = QCheckBox("Näytä renderöinnin esikatselu")
        self.preview = QLabel("Odotetaan renderöinnin ensimmäistä ruutua…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_toggle.toggled.connect(self.preview.setVisible)
        layout.addWidget(self.preview_toggle)
        layout.addWidget(self.preview)
        self.preview_toggle.hide()
        self.preview.hide()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.stage = None
        self.started = self.stage_started = self.updated = monotonic()

    def begin(self):
        self.timer.stop()
        self.history.clear()
        self.preview_toggle.hide()
        self.preview.hide()
        self.preview.setText("Odotetaan renderöinnin ensimmäistä ruutua…")
        self.stage = None
        self.started = self.stage_started = self.updated = monotonic()
        self.update_progress(dict(stage="starting", detail="Käynnistetään latausprosessia…"))
        self.timer.start()

    def update_preview(self, image):
        try:
            data = b64decode(image, validate=True)
        except (ValueError, TypeError):
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data, "JPEG"):
            self.preview.setPixmap(pixmap)

    def update_progress(self, event):
        now = monotonic()
        stage = event["stage"]
        if stage == "render":
            self.preview_toggle.show()
            self.preview.setVisible(self.preview_toggle.isChecked())
        if self.stage != stage:
            if self.stage is not None:
                self.history.appendPlainText(f"{STAGES.get(self.stage, self.stage)}: {now - self.stage_started:.1f} s")
            self.stage, self.stage_started = stage, now
        self.updated = now
        detail = str(event.get("detail") or "")
        speed = event.get("speed")
        eta = event.get("eta")
        if isinstance(speed, (int, float)) and speed > 0:
            detail += f" · {speed / 1_000_000:.2f} MB/s"
        if isinstance(eta, (int, float)) and eta >= 0:
            detail += f" · jäljellä noin {eta:.0f} s"
        self.phase.setText(f"{STAGES.get(stage, stage)}: {detail}")
        percent = event.get("percent")
        if isinstance(percent, (int, float)) and 0 <= percent <= 100:
            self.bar.setRange(0, 100)
            self.bar.setValue(round(percent))
            self.bar.setFormat("Työvaihe %p%")
        else:
            self.bar.setRange(0, 0)
        self.refresh()

    def refresh(self):
        now = monotonic()
        self.timing.setText(f"Yhteensä {now - self.started:.0f} s · vaihe {now - self.stage_started:.0f} s"
                            f" · viimeisin tilapäivitys {now - self.updated:.0f} s sitten")

    def finish(self, success):
        self.timer.stop()
        now = monotonic()
        if self.stage is not None:
            self.history.appendPlainText(f"{STAGES.get(self.stage, self.stage)}: {now - self.stage_started:.1f} s")
        self.history.appendPlainText(f"{'Valmis' if success else 'Epäonnistui'} · yhteensä {now - self.started:.1f} s")
        self.phase.setText("Valmis" if success else "Lataus epäonnistui – katso virhe alta")
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if success else 0)
        self.bar.setFormat("Valmis" if success else "Virhe")
        self.refresh()
