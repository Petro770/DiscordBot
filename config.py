"""Keskitetyt asetukset ja konstantit."""
from typing import Optional
import math
import os
import sys
from pathlib import Path
from dotenv import dotenv_values, load_dotenv

DOTENV_PATH = Path(__file__).resolve().with_name(".env")
DOTENV_STARTUP_VALUES = dotenv_values(DOTENV_PATH, interpolate=False, encoding="utf-8-sig")
# Older updaters passed the entire environment without identifying its origin.
_legacy_restart = (
    "--show-after-update" in sys.argv and "--fresh-restart-environment" not in sys.argv
)
_dotenv_keys = {key.upper() if os.name == "nt" else key
                for key, value in DOTENV_STARTUP_VALUES.items() if value is not None}
INHERITED_ENV_KEYS = frozenset(os.environ) - (_dotenv_keys if _legacy_restart else set())
load_dotenv(DOTENV_PATH, override=_legacy_restart, encoding="utf-8-sig")
DOTENV_ADDED_VALUES = {
    key: value for key, value in os.environ.items() if key not in INHERITED_ENV_KEYS
}

BOT_VERSION = "1.3.1"

# Discord
TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
def require_discord_token() -> str:
    if not TOKEN:
        raise ValueError("Aseta DISCORD_TOKEN .env-tiedostoon tai ympäristömuuttujaksi.")
    return TOKEN


_raw = os.getenv("TARGET_CHANNEL_ID", "").strip()
TARGET_CHANNEL_ID: Optional[int] = int(_raw) if _raw else None
ATTACHMENT_INDEX_CHANNEL_IDS = frozenset(
    int(channel_id.strip())
    for channel_id in os.getenv("ATTACHMENT_INDEX_CHANNEL_IDS", _raw).split(",")
    if channel_id.strip()
)
try:
    REPOST_WARNING_THRESHOLD = float(os.getenv("REPOST_WARNING_THRESHOLD", "90"))
except ValueError as exc:
    raise ValueError("REPOST_WARNING_THRESHOLD pitää antaa prosenttilukuna, esimerkiksi 92.5.") from exc
if not 0 <= REPOST_WARNING_THRESHOLD <= 100:
    raise ValueError("REPOST_WARNING_THRESHOLD pitää olla välillä 0–100.")
REACTION_EMOJI = "👽"
URL_REACTION_EMOJI = "🎬"
MEME_TEXT = "Tulostus valmis!"
REPLY_DELETE_AFTER = 5 * 60  # Sekuntia
STATUS_DELETE_DELAY = int(os.getenv("STATUS_DELETE_DELAY", "3"))


# Tulostin
PRINTER_NAME = "CITIZEN CT-S310II"

# Rate limit
MAX_PRINTS_PER_MINUTE = 2
DELAY_BETWEEN_PRINTS = 8
MAX_QUEUE_SIZE = 5

# Kuvatiedostopäätteet
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

# Oletussäilytys päivinä
MESSAGE_RETENTION_DAYS = int(os.getenv("MESSAGE_RETENTION_DAYS", "").strip() or "30")

UNTRACKED_BOT_MESSAGE_CLEANUP_MODE = os.getenv("UNTRACKED_BOT_MESSAGE_CLEANUP_MODE", "preview").strip().lower()
if UNTRACKED_BOT_MESSAGE_CLEANUP_MODE not in {"off", "preview", "delete"}:
    raise ValueError("UNTRACKED_BOT_MESSAGE_CLEANUP_MODE pitää olla off, preview tai delete.")
UNTRACKED_BOT_MESSAGE_RETENTION_HOURS = int(os.getenv("UNTRACKED_BOT_MESSAGE_RETENTION_HOURS", "24"))
if UNTRACKED_BOT_MESSAGE_RETENTION_HOURS <= 0:
    raise ValueError("UNTRACKED_BOT_MESSAGE_RETENTION_HOURS pitää olla positiivinen.")
_cleanup_channel = os.getenv("UNTRACKED_BOT_MESSAGE_CHANNEL_ID", "").strip()
UNTRACKED_BOT_MESSAGE_CHANNEL_ID = int(_cleanup_channel) if _cleanup_channel else TARGET_CHANNEL_ID

# Siivousintervalli sekunteina (300 = 5 min)
CLEANUP_INTERVAL = int(os.getenv("CLEANUP_INTERVAL", "300"))

# ============================================================
# OMINAISUUKSET
# ============================================================

def _env_bool(key: str, default: bool = True) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _ollama_timeout(key: str, default: float) -> float:
    try:
        seconds = float(os.getenv(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key}: anna positiivinen aikaraja sekunteina.") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{key}: anna positiivinen aikaraja sekunteina.")
    return seconds


OLLAMA_CONNECT_TIMEOUT_SECONDS = _ollama_timeout("OLLAMA_CONNECT_TIMEOUT_SECONDS", 3)
OLLAMA_DISCOVERY_TIMEOUT_SECONDS = _ollama_timeout("OLLAMA_DISCOVERY_TIMEOUT_SECONDS", 5)
OLLAMA_MODEL_TIMEOUT_SECONDS = _ollama_timeout("OLLAMA_MODEL_TIMEOUT_SECONDS", 40)
OLLAMA_TOTAL_TIMEOUT_SECONDS = _ollama_timeout("OLLAMA_TOTAL_TIMEOUT_SECONDS", 120)
ENABLE_OLLAMA = _env_bool("ENABLE_OLLAMA", default=False)
OLLAMA_RECENT_MESSAGES = int(os.getenv("OLLAMA_RECENT_MESSAGES", "").strip() or "12")
if not 0 <= OLLAMA_RECENT_MESSAGES <= 30:
    raise ValueError("OLLAMA_RECENT_MESSAGES pitää olla välillä 0–30.")
OLLAMA_TRACE_ENABLED = _env_bool("OLLAMA_TRACE_ENABLED", default=False)
OLLAMA_INSTRUCTIONS_FILE = os.getenv("OLLAMA_INSTRUCTIONS_FILE", "").strip()
OLLAMA_HOSTS = tuple(
    host.strip().rstrip("/")
    for host in os.getenv(
        "OLLAMA_HOSTS",
        "http://192.168.1.11:11434,http://192.168.1.12:11434,http://192.168.1.13:11434",
    ).split(",")
    if host.strip()
)
def _ollama_model_list(key: str) -> tuple[tuple[str, ...], frozenset[str]]:
    entries = [item.strip() for item in os.getenv(key, "").split(",")]
    models = tuple(dict.fromkeys(item for item in entries if item and not item.startswith("!")))
    excluded = frozenset(item[1:].strip() for item in entries if item.startswith("!") and item[1:].strip())
    return models, excluded


OLLAMA_MODELS, OLLAMA_EXCLUDED_MODELS = _ollama_model_list("OLLAMA_MODELS")
OLLAMA_CHAT_PRIORITY, OLLAMA_CHAT_EXCLUDED = _ollama_model_list("OLLAMA_CHAT_PRIORITY")
OLLAMA_VISION_PRIORITY, OLLAMA_VISION_EXCLUDED = _ollama_model_list("OLLAMA_VISION_PRIORITY")
_ollama_channel_ids = os.getenv("OLLAMA_CHANNEL_IDS")
OLLAMA_CHANNEL_SOURCE = "TARGET_CHANNEL_ID" if _ollama_channel_ids is None else "OLLAMA_CHANNEL_IDS"
OLLAMA_CHANNEL_IDS = frozenset(
    int(channel_id.strip())
    for channel_id in (_raw if _ollama_channel_ids is None else _ollama_channel_ids).split(",")
    if channel_id.strip()
)

ENABLE_IMAGE_PRINTING = _env_bool("ENABLE_IMAGE_PRINTING", default=True)
ENABLE_YOUTUBE = _env_bool("ENABLE_YOUTUBE", default=True)
ENABLE_INSTAGRAM = _env_bool("ENABLE_INSTAGRAM", default=True)
ENABLE_X = _env_bool("ENABLE_X", default=True)
ENABLE_TIKTOK = _env_bool("ENABLE_TIKTOK", default=True)
ENABLE_TWITCH = _env_bool("ENABLE_TWITCH", default=True)
ENABLE_SOUNDCLOUD = _env_bool("ENABLE_SOUNDCLOUD", default=True)
ENABLE_SOUNDCLOUD_VIDEO = _env_bool("ENABLE_SOUNDCLOUD_VIDEO", default=True)
STATUS_LOG_MODE = _env_bool("STATUS_LOG_MODE", default=True)
ENABLE_VIDEO_COMPRESS = _env_bool("ENABLE_VIDEO_COMPRESS", default=True)
VIDEO_COMPRESS_TARGET_MB = float(os.getenv("VIDEO_COMPRESS_TARGET_MB", "9.2"))


# ============================================================
# KUVANTULOSTUS (reaktio-ohjattu)
# ============================================================

# Valitut emoji-reaktiot (pilkuin eroteltu)
raw = os.getenv("PRINT_EMOJIS", "🖨️,✅")
PRINT_EMOJIS = tuple(
    e.strip().rstrip('\ufe0f') for e in raw.split(",") if e.strip()
) or ("🖨️",)  # fallback


# Kuinka kauan odotetaan (sekunteja)
PRINT_TIMEOUT = int(os.getenv("PRINT_TIMEOUT", "300"))
