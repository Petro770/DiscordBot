"""Opt-in local JSONL trace for diagnosing Discord replies."""
import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config
from core.logging import log


_trace = logging.getLogger("ollama.trace")
_trace.propagate = False
_trace.setLevel(logging.INFO)


def setup_trace():
    if not config.OLLAMA_TRACE_ENABLED or _trace.handlers:
        return
    path = Path(__file__).resolve().parents[1] / "core" / "ollama_trace.jsonl"
    try:
        handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    except OSError as exc:
        log.warning("Ollama: jäljityslokia ei saatu avattua (%s)", type(exc).__name__)
        return
    _trace.addHandler(handler)
    log.info("Ollama: jäljitysloki käytössä | tiedosto=%s", path)


def trace(event: str, message_id: int | None, **fields):
    if not _trace.handlers:
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "message_id": message_id,
        **fields,
    }
    _trace.info("%s", json.dumps(entry, ensure_ascii=False))
