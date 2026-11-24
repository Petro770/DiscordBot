"""Keskitetyt asetukset ja konstantit."""
import math
import os
from dotenv import load_dotenv

load_dotenv()

BOT_VERSION = "1.0.7"

# Discord
TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
_raw = os.getenv("TARGET_CHANNEL_ID", "").strip()
TARGET_CHANNEL_ID: int | None = int(_raw) if _raw else None
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

# Oletussäilytys päivinä (365 = 1 vuosi)
MESSAGE_RETENTION_DAYS = int(os.getenv("MESSAGE_RETENTION_DAYS", "365"))

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
_ollama_model_entries = tuple(
    model.strip() for model in os.getenv("OLLAMA_MODELS", "").split(",") if model.strip()
)
OLLAMA_MODELS = tuple(model for model in _ollama_model_entries if not model.startswith("!"))
OLLAMA_EXCLUDED_MODELS = frozenset(
    model[1:].strip() for model in _ollama_model_entries if model.startswith("!")
)
OLLAMA_CHAT_PRIORITY = tuple(dict.fromkeys(
    model.strip() for model in os.getenv("OLLAMA_CHAT_PRIORITY", "").split(",") if model.strip()
))
OLLAMA_VISION_PRIORITY = tuple(dict.fromkeys(
    model.strip() for model in os.getenv("OLLAMA_VISION_PRIORITY", "").split(",") if model.strip()
))
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
