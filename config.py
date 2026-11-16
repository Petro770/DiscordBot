"""Keskitetyt asetukset ja konstantit."""
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
REACTION_EMOJI = "👽"
URL_REACTION_EMOJI = "🎬"
MEME_TEXT = "Bogos Binted!"
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


ENABLE_IMAGE_PRINTING = _env_bool("ENABLE_IMAGE_PRINTING", default=True)
ENABLE_YOUTUBE = _env_bool("ENABLE_YOUTUBE", default=True)
ENABLE_INSTAGRAM = _env_bool("ENABLE_INSTAGRAM", default=True)
ENABLE_X = _env_bool("ENABLE_X", default=True)
ENABLE_TIKTOK = _env_bool("ENABLE_TIKTOK", default=True)
ENABLE_TWITCH = _env_bool("ENABLE_TWITCH", default=True)
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
