"""Live Ollama request diagnostics for the desktop launcher."""
import json
import logging
from datetime import datetime

from PySide6.QtCore import QObject, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from bot.ollama_trace import TEXT_FIELDS, monitor_log


_LABELS = {
    "discord_input": "Pyyntö vastaanotettu",
    "waiting_turn": "Odottaa edellistä viestiä",
    "waiting_worker": "Odottaa käsittelypaikkaa",
    "preparing": "Valmistelee pyyntöä",
    "model_input": "Mallisyöte valmis",
    "waiting_host": "Odottaa palvelinta",
    "host_selected": "Palvelin valittu",
    "discovery_error": "Mallilistan haku epäonnistui",
    "image_error": "Kuvan valmistelu epäonnistui",
    "model_capabilities_unknown": "Mallin kykyjä ei voitu vahvistaa",
    "model_skipped": "Malli ohitettu",
    "model_attempt": "Odottaa mallin vastausta",
    "model_response": "Malli vastasi",
    "model_response_rejected": "Vastaus hylättiin",
    "model_error": "Malliyritys epäonnistui",
    "model_timeout": "Aikakatkaisu",
    "parsed_response": "Vastaus käsitelty",
    "discord_output": "Lähetetty Discordiin",
    "discord_send_error": "Lähetys epäonnistui",
    "queue_full": "Jono täynnä",
    "cancelled": "Peruttu",
    "failed": "Käsittelyvirhe",
}
_OUTCOMES = {"success": "Valmis", "fallback": "Lähetetty ilman mallivastausta", "send_error": "Lähetys epäonnistui"}
_TERMINAL = {"finished", "queue_full", "cancelled", "failed"}
_PRIVATE_FIELDS = TEXT_FIELDS | {"style", "session_style", "channel_name"}


class _MonitorSignal(QObject):
    received = Signal(object)


class _MonitorHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        self.signal.received.emit(record.ollama_event)


def _label(event):
    if event["event"] == "models_exhausted":
        if event["has_image"] and not event["attempts"]:
            return "Kuvamallia ei löytynyt"
        if not event["attempts"]:
            return "Käyttökelpoista tekstimallia ei löytynyt"
        return "Mallikierros päättyi ilman vastausta"
    if event["event"] == "finished":
        return _OUTCOMES[event["outcome"]]
    return _LABELS.get(event["event"], event["event"])


class AiMonitor(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI-keskustelut")
        self.resize(960, 570)
        self._requests = {}
        self._channels = QListWidget()
        self._turns = QListWidget()
        self._timeline = QPlainTextEdit(readOnly=True)
        self._details = QPlainTextEdit(readOnly=True)
        self._context = QLabel()
        self._context.setTextFormat(Qt.TextFormat.PlainText)
        self._context.setWordWrap(True)
        self._copy = QPushButton("Kopioi vianetsintätiedot")
        self._copy.clicked.connect(self._copy_diagnostics)
        self._copy_text = QPushButton("Kopioi vianetsintätiedot ja viestitekstit…")
        self._copy_text.clicked.connect(self._copy_with_text)
        self._channels.currentItemChanged.connect(self._refresh_turns)
        self._turns.currentItemChanged.connect(self._refresh_details)

        lists = QWidget()
        left = QVBoxLayout(lists)
        left.addWidget(QLabel("Keskustelut"))
        left.addWidget(self._channels)
        left.addWidget(QLabel("Pyynnöt"))
        left.addWidget(self._turns)
        detail = QWidget()
        right = QVBoxLayout(detail)
        right.addWidget(self._context)
        tabs = QTabWidget()
        tabs.addTab(self._timeline, "Aikajana")
        tabs.addTab(self._details, "Tekstijäljitys")
        right.addWidget(tabs, 1)
        right.addWidget(self._copy)
        right.addWidget(self._copy_text)
        splitter = QSplitter()
        splitter.addWidget(lists)
        splitter.addWidget(detail)
        splitter.setSizes([325, 635])
        QHBoxLayout(self).addWidget(splitter)

        self._signal = _MonitorSignal(self)
        self._signal.received.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        handler = _MonitorHandler(self._signal)
        monitor_log.addHandler(handler)
        self.destroyed.connect(lambda: monitor_log.removeHandler(handler))
        self._refresh_details()

    @Slot(object)
    def _receive(self, event):
        message_id = event["message_id"]
        if event["event"] == "discord_input":
            self._requests[message_id] = [event]
        elif message_id in self._requests:
            events = self._requests[message_id]
            if len(events) >= 150:
                del events[1]
            events.append(event)
        else:
            return

        if len(self._requests) > 150:
            oldest = next((key for key, events in self._requests.items()
                           if events[-1]["event"] in _TERMINAL), None)
            if oldest is not None:
                del self._requests[oldest]
        self._refresh_channels()

    @staticmethod
    def _selected(widget):
        item = widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    @staticmethod
    def _fill(widget, rows, selected):
        with QSignalBlocker(widget):
            widget.clear()
            for key, text in rows:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, key)
                widget.addItem(item)
                if key == selected:
                    widget.setCurrentItem(item)
            if widget.currentRow() < 0 and widget.count():
                widget.setCurrentRow(0)

    def _refresh_channels(self):
        channels = {}
        for events in reversed(self._requests.values()):
            first, latest = events[0], events[-1]
            channel = channels.setdefault(first["channel_id"], [first, latest, 0])
            channel[2] += latest["event"] not in _TERMINAL
        rows = []
        for channel_id, (first, latest, active) in channels.items():
            name = first.get("channel_name") or ("Yksityisviesti" if first["private"] else "Kanava")
            rows.append((channel_id, f"{name} · {channel_id}\n{active} kesken · {_label(latest)}"))
        self._fill(self._channels, rows, self._selected(self._channels))
        self._refresh_turns()

    def _refresh_turns(self):
        channel_id = self._selected(self._channels)
        rows = ((key, f"{key} · {_label(events[-1])}")
                for key, events in reversed(self._requests.items()) if events[0]["channel_id"] == channel_id)
        self._fill(self._turns, rows, self._selected(self._turns))
        self._refresh_details()

    def _events(self):
        return self._requests.get(self._selected(self._turns), [])

    def _refresh_details(self):
        events = self._events()
        self._copy.setEnabled(bool(events))
        self._copy_text.setEnabled(any(TEXT_FIELDS.intersection(event) - {"system"} for event in events))
        model_input = next((event for event in events if event["event"] == "model_input"), {})
        parsed = next((event for event in events if event["event"] == "parsed_response"), {})
        delivered = bool(events and events[-1].get("outcome") == "success")
        target = (parsed.get("text_target") if delivered else None) or model_input.get("text_target")
        style = next((event.get("style") for event in reversed(events)
                      if event["event"] == "parsed_response" and event.get("style")), None)
        self._context.setText(
            f"Tekstimalli: {' / '.join(target) if target else '–'}\n"
            f"Tyyliohje: {style or model_input.get('session_style') or '–'} · Muistivuorot: {model_input.get('history_turns', '–')}"
            f" · Taustaviestit: {model_input.get('recent_messages', '–')} · Henkilöt: {model_input.get('people_count', '–')}"
            if events else "AI-pyyntöjä ei ole vielä vastaanotettu."
        )
        lines = []
        details = []
        for event in events:
            time = datetime.fromisoformat(event["timestamp"]).astimezone().strftime("%H:%M:%S")
            data = " · ".join(str(event[key]) for key in ("host", "model", "reason", "error", "status")
                              if event.get(key) is not None)
            elapsed = f" · {event['elapsed_seconds']:.2f} s" if "elapsed_seconds" in event else ""
            lines.append(f"{time}  {_label(event)}" + (f" · {data}" if data else "") + elapsed)
            fields = {key: event[key] for key in ("user", "content", "history") if key in event}
            if fields and event["event"] in {"model_input", "model_response", "discord_output"}:
                details.append(f"{_label(event)}\n" + "\n".join(
                    value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
                    for value in fields.values()
                ))
        self._timeline.setPlainText("\n".join(lines))
        self._details.setPlainText("\n\n".join(details) or "Tekstijäljitys vaatii OLLAMA_TRACE_ENABLED=true.")

    def _copy_with_text(self):
        answer = QMessageBox.question(
            self, "Kopioi viestitekstit",
            "Kopio voi sisältää yksityisviestejä, nimiä ja mainintoja. Tarkista tiedot ennen jakamista.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._copy_diagnostics(include_text=True)

    def _copy_diagnostics(self, include_text=False):
        excluded = _PRIVATE_FIELDS - {"content", "user", "history"} if include_text else _PRIVATE_FIELDS
        rows = [{key: value for key, value in event.items() if key not in excluded}
                for event in self._events()]
        QApplication.clipboard().setText("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
