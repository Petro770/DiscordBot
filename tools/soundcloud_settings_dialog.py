"""SoundCloud clipboard video preferences."""
from dataclasses import asdict
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFormLayout, QSpinBox, QComboBox,
    QCheckBox, QGroupBox, QDialogButtonBox, QMessageBox, QScrollArea, QWidget,
)
from tools.soundcloud_video_preview import SoundCloudVideoPreview
from tools.soundcloud_video_settings import MAX_VIDEO_BANDS, SoundCloudVideoSettings


class SoundCloudSettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("SoundCloud-videon oletusasetukset")
        self.resize(880, 620)
        layout = QVBoxLayout(self)
        info = QLabel(
            "Asetukset koskevat seuraavia leikepöydältä tehtäviä SoundCloud-videoita. "
            "Suurempi FPS, resoluutio ja kaistamäärä hidastavat muodostusta. "
            "Äänen laatu riippuu myös SoundCloudin lähteestä. Kokoraja on 150 MB."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        self.controls = {}
        for name, label, low, high, suffix, tip in (
            ("fps", "FPS-tavoite", 1, 60, " fps", "Aaltomuodon ja videon ruutunopeus."),
            ("resolution", "Videon sivun pituus", 320, 1920, " px", "Neliövideo; parillinen pikselimäärä."),
            ("audio_kbps", "Äänen bittinopeus", 48, 320, " kbit/s", "MP3-välitiedoston ja MP4:n AAC-äänen tavoite."),
            ("crf", "Videon laatu (CRF)", 0, 51, "", "Pienempi arvo = parempi laatu ja suurempi tiedosto. Oletus 24."),
            ("bands", "Visuaalisten taajuuskaistojen määrä", 1, MAX_VIDEO_BANDS, "", "Kolme kaistaa käyttää alkuperäistä basso/keskiääni/diskantti-jakoa."),
            ("intro_seconds", "Otsikon ja esittäjän näyttöaika", 0, 30, " s", "0 piilottaa otsikon ja esittäjän."),
            ("wave_opacity", "Aaltomuodon taustan peittävyys", 0, 255, "", "0 = läpinäkyvä, 255 = peittävä."),
            ("wave_line_width", "Viivan paksuus", 1, 12, " px", "Kaikkien bändien viivan paksuus 640 px:n peruskoossa. Skaalautuu videon resoluution mukana."),
            ("wave_amplitude", "Aaltojen korkeus", 1, 48, " px", "Kunkin kaistan normalisoitu enimmäiskorkeus."),
            ("wave_window_percent", "Aaltomuodon aikaikkuna", 25, 300, " %", "100 % käyttää alkuperäisiä 1,5–3,4 sekunnin aikaikkunoita."),
            ("encode_timeout", "Renderöinnin jumittumisraja", 30, 7200, " s", "Keskeyttää renderöinnin, jos uusia ruutuja ei saada tässä ajassa. Koko videon muodostus saa kestää pidempään."),
        ):
            control = QSpinBox()
            control.setRange(low, high)
            control.setSuffix(suffix)
            control.setToolTip(tip)
            if name == "resolution":
                control.setSingleStep(2)
            form.addRow(label, control)
            self.controls[name] = control
        background = QCheckBox("Näytä aaltomuodon taustapaneeli")
        background.setToolTip("Oletuksena viivat piirretään suoraan kansikuvan päälle.")
        form.addRow(background)
        self.controls["wave_background"] = background
        background.toggled.connect(self.controls["wave_opacity"].setEnabled)
        preset = QComboBox()
        preset.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        preset.setToolTip("Hitaampi enkoodaus pakkaa yleensä tehokkaammin samalla CRF-laadulla.")
        form.addRow("Enkoodausnopeus", preset)
        self.controls["preset"] = preset
        compress = QCheckBox("Pakkaa automaattisesti, jos 150 MB ylittyy")
        compress.setToolTip("Lisäpakkaus voi pienentää resoluutiota sekä äänen ja videon bittinopeutta.")
        form.addRow(compress)
        self.controls["auto_compress"] = compress
        scroll.setWidget(body)
        columns = QHBoxLayout()
        columns.addWidget(scroll, stretch=1)
        preview = SoundCloudVideoPreview(settings, self)
        preview_column = QVBoxLayout()
        preview_column.addWidget(preview)
        floor_group = QGroupBox("Beatfloor")
        floor_form = QFormLayout(floor_group)
        enabled = QCheckBox("Näytä iskulinjat")
        self.controls["beat_floor_enabled"] = enabled
        floor_form.addRow(enabled)
        accent = QCheckBox("Korosta joka neljäs isku")
        self.controls["beat_floor_accent_every_four"] = accent
        floor_form.addRow(accent)
        for name, label, low, high, suffix in (
            ("beat_floor_x_offset", "Vaakasiirto", -160, 160, " px"),
            ("beat_floor_y_offset", "Pystysiirto", -105, 20, " px"),
            ("beat_floor_height", "Iskulinjojen korkeus", 12, 256, " px"),
            ("beat_floor_far_width_percent", "Horisontin leveys", 10, 1000, " %"),
            ("beat_floor_near_width_percent", "Etualan leveys", 25, 150, " %"),
        ):
            control = QSpinBox()
            control.setRange(low, high)
            control.setSuffix(suffix)
            self.controls[name] = control
            floor_form.addRow(label, control)
        self.controls["beat_floor_height"].setToolTip(
            "Horisontin ja etureunan välinen pystyetäisyys 640 × 640 -peruskoossa."
        )
        self.controls["beat_floor_y_offset"].setToolTip(
            "Siirtää horisonttia ja etureunaa yhdessä. Negatiivisempi arvo nostaa iskulinjoja."
        )
        preview_column.addWidget(floor_group)
        columns.addLayout(preview_column)

        def update_floor():
            preview.set_floor_settings({
                name: control.isChecked() if isinstance(control, QCheckBox) else control.value()
                for name, control in self.controls.items() if name.startswith("beat_floor_")
            })

        enabled.toggled.connect(update_floor)
        accent.toggled.connect(update_floor)
        for name, control in self.controls.items():
            if name.startswith("beat_floor_") and isinstance(control, QSpinBox):
                control.valueChanged.connect(update_floor)
        layout.addLayout(columns)
        self.finished.connect(preview.stop)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.button(QDialogButtonBox.Save).setText("Tallenna")
        buttons.button(QDialogButtonBox.Cancel).setText("Peruuta")
        buttons.button(QDialogButtonBox.RestoreDefaults).setText("Palauta oletukset")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda: self.populate(SoundCloudVideoSettings()))
        layout.addWidget(buttons)
        try:
            current = SoundCloudVideoSettings.from_json(settings.value("clipboard/soundcloudVideoSettings", "{}"))
        except (ValueError, TypeError):
            current = SoundCloudVideoSettings()
        self.populate(current)
        update_floor()

    def populate(self, values):
        for name, value in asdict(values).items():
            control = self.controls[name]
            if isinstance(control, QCheckBox):
                control.setChecked(value)
            elif isinstance(control, QComboBox):
                control.setCurrentText(value)
            else:
                control.setValue(value)

        self.controls["wave_opacity"].setEnabled(self.controls["wave_background"].isChecked())

    def save(self):
        values = {}
        for name, control in self.controls.items():
            values[name] = (control.isChecked() if isinstance(control, QCheckBox)
                            else control.currentText() if isinstance(control, QComboBox)
                            else control.value())
        try:
            result = SoundCloudVideoSettings(**values)
        except ValueError as error:
            QMessageBox.warning(self, "Tarkista asetukset", str(error))
            return
        self.settings.setValue("clipboard/soundcloudVideoSettings", result.to_json())
        self.settings.sync()
        if self.settings.status() != self.settings.NoError:
            QMessageBox.warning(self, "Tallennus epäonnistui", "Asetuksia ei voitu tallentaa.")
            return
        self.accept()
