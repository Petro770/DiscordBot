"""Opt-in newline JSON progress from the clipboard worker to its GUI."""
import json
import sys
from time import monotonic

_enabled = False
_PREFIX = "CLIPBOARD_PROGRESS="


def enable_stdout_progress():
    global _enabled
    _enabled = True


def report(stage, detail="", percent=None, **metrics):
    if _enabled:
        print(_PREFIX + json.dumps(dict(stage=stage, detail=detail, percent=percent, **metrics),
                                   ensure_ascii=True, allow_nan=False), flush=True)


def download_hook():
    last_update = 0.0

    def update(data):
        nonlocal last_update
        if data.get("status") == "finished":
            report("audio", "Lataus valmis, muunnetaan ääntä…")
            return
        now = monotonic()
        if data.get("status") != "downloading" or now - last_update < 0.5:
            return
        last_update = now
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes", 0)
        report("download", "Ladataan äänitiedostoa", 100 * downloaded / total if total else None,
               downloaded=downloaded, total=total, speed=data.get("speed"), eta=data.get("eta"))
    return update


class ProgressReader:
    def __init__(self):
        self.buffer = b""

    def feed(self, chunk):
        self.buffer += chunk
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()[-65536:]
        events = []
        for line in lines:
            if not line.startswith(_PREFIX.encode()):
                continue
            try:
                event = json.loads(line[len(_PREFIX):])
                if isinstance(event, dict) and isinstance(event.get("stage"), str):
                    events.append(event)
            except (ValueError, UnicodeError):
                pass
        return events
