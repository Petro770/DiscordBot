"""TikTok-videoiden lataus yt-dlp:llä."""
import os
import re
import asyncio
import tempfile
import shutil

import yt_dlp

from core.logging import log
from core.models import VideoInfo, NonRetryableError

from downloaders.base import ffmpeg_executables

DISCORD_FILE_LIMIT = 25 * 1024 * 1024


# ============================================================
# URL-TUNNISTUS
# ============================================================

TIKTOK_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9_.]+)/video/(\d+)",
    re.IGNORECASE,
)

# Lyhyet linkit (vt.tiktok.com) tunnistetaan erikseen
TIKTOK_SHORT_URL = re.compile(
    r"https?://(?:vt|vm)\.tiktok\.com/[A-Za-z0-9]+/?",
    re.IGNORECASE,
)


def is_tiktok(url: str) -> bool:
    return bool(TIKTOK_URL_PATTERN.search(url) or TIKTOK_SHORT_URL.search(url))


def extract_tiktok_url(url: str) -> str | None:
    """Palauttaa siistitun TikTok-URL:n."""
    m = TIKTOK_URL_PATTERN.search(url)
    if m:
        username, video_id = m.group(1), m.group(2)
        return f"https://www.tiktok.com/@{username}/video/{video_id}"

    # Lyhyt linkki – käytetään sellaisenaan (yt_dlp seuraa redirectin)
    if TIKTOK_SHORT_URL.search(url):
        return url

    return None


# ============================================================
# VIRHETARKISTUS
# ============================================================

TIKTOK_NON_RETRYABLE = re.compile(
    r"video unavailable|"
    r"not found|"
    r"removed by|"
    r"private account|"
    r"age[-\s]restricted|"
    r"unavailable",
    re.IGNORECASE,
)


def _check_non_retryable(error: Exception) -> NonRetryableError | None:
    msg = str(error)
    if TIKTOK_NON_RETRYABLE.search(msg):
        return NonRetryableError(
            message=msg,
            user_facing="⚠️ TikTok-video ei ole saatavilla (poistettu tai yksityinen).",
        )
    return None


# ============================================================
# LATAUS
# ============================================================

def _download_sync(url: str) -> VideoInfo | None:
    """Synchroninen lataus. Palauttaa VideoInfo-objektin."""
    ffmpeg_path, _ = ffmpeg_executables()
    tmpdir = tempfile.mkdtemp(prefix="tt_")
    final_path = None  # ← trackaa

    try:

        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
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
            log.error("TikTok-lataus epäonnistui: %s", e)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None

        # Etsi ladattu tiedosto
        files = [f for f in os.listdir(tmpdir) if f.endswith(".mp4")]
        if not files:
            # Ehkä gif/jpg
            files = [f for f in os.listdir(tmpdir) if f.lower().endswith((".jpg", ".jpeg", ".webp", ".gif"))]

        if not files:
            log.warning("TikTok: Ei mediatiedostoa löytynyt")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None

        filepath = os.path.join(tmpdir, files[0])
        filename = f"tiktok_{files[0]}"
        is_video = files[0].endswith(".mp4")

        # Siirra pysyvään paikkaan
        import uuid
        unique_name = f"tiktok_{uuid.uuid4().hex[:8]}_{files[0]}"
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

        log.info("✅ TikTok-lataus valmis: %s (%.1f MB)",
                 filename, os.path.getsize(final_path) / (1024 * 1024))

        return VideoInfo(
            filepath=final_path,
            filename=filename,
            title=title,
            uploader=uploader,
            description=description,
            source_url=url,
            is_video=is_video,
        )
    except NonRetryableError:
        raise
    except Exception:
        if final_path and os.path.exists(final_path):
            os.unlink(final_path)
        raise
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def download_tiktok(url: str) -> VideoInfo | None:
    """
    Lataa TikTok-videon asynkisesti.
    Heittää NonRetryableError jos video ei ole saatavilla.
    Palauttaa VideoInfo:n tai None.
    """
    clean = extract_tiktok_url(url)
    if not clean:
        log.warning("TikTok: Ei validia URL:ää: %s", url[:80])
        return None

    log.info("🎵 TikTok-lataus aloitettu: %s", clean)

    try:
        result = await asyncio.to_thread(_download_sync, clean)
        if result:
            log.info("✅ TikTok: %s", result.filename)
        return result
    except NonRetryableError:
        log.warning("🚫 TikTok: Video ei ole saatavilla: %s", clean)
        raise

