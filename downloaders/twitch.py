"""Twitch-klipien ja VOD:ien lataus yt-dlp:llä."""
import os
import re
import asyncio
import shutil
import tempfile

import yt_dlp

from core.logging import log
from core.models import VideoInfo, NonRetryableError

from downloaders.base import ffmpeg_executables

DISCORD_FILE_LIMIT = 25 * 1024 * 1024  # 25 MB

# ============================================================
# URL-TUNNISTUS
# ============================================================

# Klipit: https://www.twitch.tv/{channel}/clip/{name}-{id}
TWITCH_CLIP_PATTERN = re.compile(
    r"https?://(?:www\.)?twitch\.tv/([A-Za-z0-9_]+)/clip/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# VOD:it: https://www.twitch.tv/videos/{id}
TWITCH_VOD_PATTERN = re.compile(
    r"https?://(?:www\.)?twitch\.tv/videos/(\d+)",
    re.IGNORECASE,
)

# VOD:it (vanha muoto): https://www.twitch.tv/{channel}/v/{id}
TWITCH_VOD_CHANNEL_PATTERN = re.compile(
    r"https?://(?:www\.)?twitch\.tv/([A-Za-z0-9_]+)/v/(\d+)",
    re.IGNORECASE,
)


def is_twitch(url: str) -> bool:
    return bool(
        TWITCH_CLIP_PATTERN.search(url)
        or TWITCH_VOD_PATTERN.search(url)
        or TWITCH_VOD_CHANNEL_PATTERN.search(url)
    )


def extract_twitch_url(url: str) -> str | None:
    """Palauttaa siistitun Twitch-URL:n."""
    # Klippi
    m = TWITCH_CLIP_PATTERN.search(url)
    if m:
        channel, clip_id = m.group(1), m.group(2)
        return f"https://www.twitch.tv/{channel}/clip/{clip_id}"

    # VOD (videos/{id})
    m = TWITCH_VOD_PATTERN.search(url)
    if m:
        return f"https://www.twitch.tv/videos/{m.group(1)}"

    # VOD ({channel}/v/{id})
    m = TWITCH_VOD_CHANNEL_PATTERN.search(url)
    if m:
        return f"https://www.twitch.tv/{m.group(1)}/v/{m.group(2)}"

    return None


# ============================================================
# VIRHETARKISTUS
# ============================================================

TWITCH_NON_RETRYABLE = re.compile(
    r"video unavailable|"
    r"not found|"
    r"clip is unavailable|"
    r"removed by|"
    r"private|"
    r"geoblocked|"
    r"age[-\s]restricted|"
    r"unavailable|"
    r"offline",
    re.IGNORECASE,
)


def _check_non_retryable(error: Exception) -> NonRetryableError | None:
    msg = str(error)
    if TWITCH_NON_RETRYABLE.search(msg):
        return NonRetryableError(
            message=msg,
            user_facing="⚠️ Twitch-video ei ole saatavilla (poistettu, yksityinen tai alueellisesti rajoitettu).",
        )
    return None


# ============================================================
# LATAUS
# ============================================================

def _download_sync(url: str) -> VideoInfo | None:
    """Synchroninen lataus. Palauttaa VideoInfo-objektin."""
    ffmpeg_path, _ = ffmpeg_executables()
    tmpdir = tempfile.mkdtemp(prefix="tw_")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": os.path.join(tmpdir, "video.%(ext)s"),
        "noplaylist": True,
        "ffmpeg_location": ffmpeg_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    }

    info_dict = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
    except Exception as e:
        non_retryable = _check_non_retryable(e)
        if non_retryable:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise non_retryable from e
        log.error("Twitch-lataus epäonnistui: %s", e)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None

    # Etsi ladattu tiedosto
    files = [f for f in os.listdir(tmpdir) if f.endswith(".mp4")]
    if not files:
        files = [f for f in os.listdir(tmpdir) if f.lower().endswith((".webm", ".mkv"))]

    if not files:
        log.warning("Twitch: Ei mediatiedostoa löytynyt")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None

    filepath = os.path.join(tmpdir, files[0])
    filename = f"twitch_{files[0]}"
    is_video = files[0].endswith((".mp4", ".webm", ".mkv"))

    # Siirra pysyvään paikkaan
    import uuid
    unique_name = f"twitch_{uuid.uuid4().hex[:8]}_{files[0]}"
    final_path = os.path.join(tempfile.gettempdir(), unique_name)

    os.replace(filepath, final_path)
    shutil.rmtree(tmpdir, ignore_errors=True)

    # --- Metadata ---
    title = info_dict.get("title", "") if info_dict else ""
    uploader = (
        f"@{info_dict.get('uploader_id') or info_dict.get('uploader', '')}"
        if info_dict else ""
    )
    description = info_dict.get("description", "") if info_dict else ""

    # source_url
    source = (info_dict.get("webpage_url") or url) if info_dict else url

    # Poista URL:t descriptionista
    description = re.sub(r"https?://\S+", "", description).strip()

    log.info("✅ Twitch-lataus valmis: %s (%.1f MB)",
             filename, os.path.getsize(final_path) / (1024 * 1024))

    return VideoInfo(
        filepath=final_path,
        filename=filename,
        title=title,
        uploader=uploader,
        description=description,
        source_url=source,
        is_video=is_video,
    )


async def download_twitch(url: str) -> VideoInfo | None:
    """Lataa Twitch-klipin tai VOD:n asynkisesti."""
    clean = extract_twitch_url(url)
    if not clean:
        log.warning("Twitch: Ei validia URL:ää: %s", url[:80])
        return None

    log.info("🎮 Twitch-lataus aloitettu: %s", clean)

    try:
        result = await asyncio.to_thread(_download_sync, clean)
        if result:
            log.info("✅ Twitch: %s", result.filename)
        return result
    except NonRetryableError:
        log.warning("🚫 Twitch: Video ei ole saatavilla: %s", clean)
        raise

