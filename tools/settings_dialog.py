"""Read-only view of the desktop launcher's effective settings."""
import platform
from dataclasses import asdict
from urllib.parse import urlsplit

from dotenv import dotenv_values
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHeaderView, QLineEdit, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QMessageBox,
)

import config
from tools.git_update import UpdateError
from tools.env_editor import EnvEditor
from tools.soundcloud_video_settings import SoundCloudVideoSettings


_DISCORD = (
    "DISCORD_TOKEN", "TARGET_CHANNEL_ID", "ATTACHMENT_INDEX_CHANNEL_IDS",
    "REPOST_WARNING_THRESHOLD", "MESSAGE_RETENTION_DAYS", "CLEANUP_INTERVAL",
    "UNTRACKED_BOT_MESSAGE_CLEANUP_MODE", "UNTRACKED_BOT_MESSAGE_RETENTION_HOURS",
    "UNTRACKED_BOT_MESSAGE_CHANNEL_ID", "STATUS_LOG_MODE", "STATUS_DELETE_DELAY",
)
_OLLAMA = (
    "ENABLE_OLLAMA", "OLLAMA_HOSTS", "OLLAMA_CHANNEL_IDS", "OLLAMA_MODELS",
    "OLLAMA_CHAT_PRIORITY", "OLLAMA_VISION_PRIORITY", "OLLAMA_RECENT_MESSAGES",
    "OLLAMA_TRACE_ENABLED", "OLLAMA_INSTRUCTIONS_FILE", "OLLAMA_CONNECT_TIMEOUT_SECONDS",
    "OLLAMA_DISCOVERY_TIMEOUT_SECONDS", "OLLAMA_MODEL_TIMEOUT_SECONDS", "OLLAMA_TOTAL_TIMEOUT_SECONDS",
)
_MEDIA = (
    "ENABLE_YOUTUBE", "ENABLE_INSTAGRAM", "ENABLE_X", "ENABLE_TIKTOK",
    "ENABLE_TWITCH", "ENABLE_SOUNDCLOUD", "ENABLE_SOUNDCLOUD_VIDEO",
    "ENABLE_VIDEO_COMPRESS", "VIDEO_COMPRESS_TARGET_MB", "ENABLE_IMAGE_PRINTING",
    "PRINT_EMOJIS", "PRINT_TIMEOUT",
)


def _safe_origin(host: str) -> str:
    try:
        parsed = urlsplit(host)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "(virheellinen osoite)"
        name = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        port = parsed.port
        return f"{parsed.scheme}://{name}" + (f":{port}" if port else "")
    except ValueError:
        return "(virheellinen osoite)"


def _display(value) -> str:
    if isinstance(value, bool):
        return "Käytössä" if value else "Pois käytöstä"
    if isinstance(value, frozenset):
        value = sorted(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(map(str, value)) or "–"
    return "–" if value is None or value == "" else str(value)


def _env_row(label, value, disk, *, key=None, fallback=None, blank_uses_default=False):
    key = key or label
    raw = config.DOTENV_STARTUP_VALUES.get(key)
    source_key = key
    if fallback and (key not in config.INHERITED_ENV_KEYS and key not in config.DOTENV_ADDED_VALUES):
        source_key = fallback
    if source_key in config.INHERITED_ENV_KEYS:
        source = "Ympäristömuuttuja"
    elif source_key in config.DOTENV_ADDED_VALUES:
        source = ".env"
        if blank_uses_default and raw is not None and not raw.strip():
            source = "Oletus (.env tyhjä)"
    else:
        source = "Oletus"
    if source_key != key:
        source = f"{source_key} · {source}"
    changed = any(
        name not in config.INHERITED_ENV_KEYS and disk.get(name) != config.DOTENV_STARTUP_VALUES.get(name)
        for name in (key, source_key)
    )
    return label, _display(value), source, "Vaatii uudelleenkäynnistyksen" if changed else ""


def settings_rows(updater, settings, clipboard_enabled):
    try:
        branch, commit = updater.current()
    except UpdateError:
        branch, commit = "", ""
    try:
        disk = dotenv_values(config.DOTENV_PATH, interpolate=False, encoding="utf-8-sig")
        env_status = "Löytyi" if config.DOTENV_PATH.is_file() else "Tiedosto puuttuu"
    except (OSError, UnicodeError):
        disk = config.DOTENV_STARTUP_VALUES
        env_status = "Tiedostoa ei voitu lukea"

    groups = {
        "Yleiset": [
            ("Botin versio", config.BOT_VERSION, "Projekti", ""),
            ("Git-haara", branch or ("Irrotettu HEAD" if commit else "Ei saatavilla"), "Git", ""),
            ("Git-commit", commit or "Ei saatavilla", "Git", ""),
            ("Python", platform.python_version(), "Prosessi", ""),
            (".env", str(config.DOTENV_PATH), "Projekti", env_status),
        ],
    }
    for title, names in (("Discord", _DISCORD), ("Ollama", _OLLAMA), ("Media ja leikepöytä", _MEDIA)):
        rows = groups[title] = []
        for name in names:
            if name == "DISCORD_TOKEN":
                value = "Asetettu" if config.TOKEN else "Puuttuu"
            elif name == "OLLAMA_HOSTS":
                value = tuple(_safe_origin(host) for host in config.OLLAMA_HOSTS)
            else:
                value = getattr(config, name)
            fallback = "TARGET_CHANNEL_ID" if name in {"ATTACHMENT_INDEX_CHANNEL_IDS", "OLLAMA_CHANNEL_IDS",
                                                       "UNTRACKED_BOT_MESSAGE_CHANNEL_ID"} else None
            rows.append(_env_row(name, value, disk, fallback=fallback,
                                 blank_uses_default=name in {"MESSAGE_RETENTION_DAYS", "OLLAMA_RECENT_MESSAGES"}))
            if name == "OLLAMA_MODELS":
                rows.append(_env_row("Ollaman mallipoissulut", config.OLLAMA_EXCLUDED_MODELS, disk, key=name))

    media = groups["Media ja leikepöytä"]
    media.append(("Leikepöytäseuranta", _display(clipboard_enabled), "Käynnissä oleva GUI", ""))
    for key, label in (("soundcloudVideo", "SoundCloud leikepöydälle MP4-videona"),
                       ("notificationSounds", "Ilmoitusäänet")):
        path = f"clipboard/{key}"
        media.append((label, _display(settings.value(path, True, type=bool)),
                      "GUI-asetukset" if settings.contains(path) else "Oletus", ""))
    path = "clipboard/soundcloudVideoSettings"
    raw = settings.value(path, "{}")
    try:
        video = SoundCloudVideoSettings.from_json(raw)
        source = "GUI-asetukset" if settings.contains(path) else "Oletus"
    except (TypeError, ValueError):
        video = SoundCloudVideoSettings()
        source = "Oletus (virheellinen GUI-asetus)"
    media.extend((f"SoundCloud-video · {name}", _display(value), source, "")
                 for name, value in asdict(video).items())
    return groups


class SettingsDialog(QDialog):
    def __init__(self, updater, settings, clipboard_enabled, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asetukset")
        self.resize(920, 560)
        self._updater = updater
        self._settings = settings
        self._clipboard_enabled = clipboard_enabled
        self._template = config.DOTENV_PATH.with_name("example.env")
        self._examples = dotenv_values(self._template, interpolate=False, encoding="utf-8-sig")
        self._rows = settings_rows(updater, settings, clipboard_enabled)
        self._tables = {}
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Hae asetuksen nimellä…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        for title, rows in self._rows.items():
            table = QTableWidget(len(rows), 5)
            table.setHorizontalHeaderLabels(["Asetus", "Käytössä oleva arvo", "Lähde", "Tila", "Esimerkki / oletus"])
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.verticalHeader().hide()
            table.setWordWrap(True)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            self._tables[title] = table
            tabs.addTab(table, title)
        self._populate()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Sulje")
        buttons.rejected.connect(self.reject)
        edit = QPushButton("Muokkaa .env…")
        buttons.addButton(edit, QDialogButtonBox.ButtonRole.ActionRole)
        edit.clicked.connect(self._edit_env)
        copy = QPushButton("Kopioi asetustiedot")
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(self._copy)
        layout.addWidget(buttons)

    def _populate(self):
        for title, rows in self._rows.items():
            table = self._tables[title]
            table.setRowCount(len(rows))
            for row, cells in enumerate(rows):
                key = cells[0]
                example = self._examples.get(key)
                if key == "DISCORD_TOKEN":
                    example = None
                elif key == "OLLAMA_HOSTS" and example:
                    example = ", ".join(_safe_origin(value.strip()) for value in example.split(","))
                for column, value in enumerate((*cells, "Tyhjä" if example == "" else example or "–")):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    table.setItem(row, column, item)
            table.resizeRowsToContents()
        self._filter(self.search.text())

    def _edit_env(self):
        try:
            editor = EnvEditor(config.DOTENV_PATH, self._template, self)
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, ".env-muokkaus", str(exc))
            return
        if editor.exec():
            self._rows = settings_rows(self._updater, self._settings, self._clipboard_enabled)
            self._populate()

    def _filter(self, text):
        query = text.strip().casefold()
        for title, table in self._tables.items():
            for index, row in enumerate(self._rows[title]):
                table.setRowHidden(index, query not in row[0].casefold())

    def _copy(self):
        blocks = ["\n".join([title, *(" | ".join(cell for cell in row if cell) for row in rows)])
                  for title, rows in self._rows.items()]
        QApplication.clipboard().setText("\n\n".join(blocks))
