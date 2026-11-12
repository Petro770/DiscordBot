"""X.com (Twitter) -videoiden lataus yt-dlp:llä."""
import os
import re
import asyncio
import shutil
import tempfile

import yt_dlp
import static_ffmpeg
from static_ffmpeg import run

from core.logging import log
from core.models import VideoInfo, NonRetryableError

static_ffmpeg.add_paths(weak=True)
_ffmpeg_path, _ = run.get_or_fetch_platform_executables_else_raise()

DISCORD_FILE_LIMIT = 25 * 1024 * 1024  # 25 MB

# ============================================================
# URL-TUNNISTUS
# ============================================================

X_URL_PATTERN = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)/status/(\d+)",
    re.IGNORECASE,
)

# t.co-pikalinkit
T_CO_URL = re.compile(
    r"https?://t\.co/[A-Za-z0-9]+",
    re.IGNORECASE,
)

# fxtwitter-mäenlinkit (esim. https://fxtwitter.com/i/status/2062797844835074525)
FXTWITTER_URL = re.compile(
    r"https?://(?:fixvx|fxtwitter|vxtwitter|fixupx)\.com/([A-Za-z0-9_]+)/status/(\d+)",
    re.IGNORECASE,
)

X_NON_RETRYABLE = re.compile(
    r"not found|private|removed|suspended|unavailable",
    re.IGNORECASE,
)

def is_x(url: str) -> bool:
    return bool(X_URL_PATTERN.search(url) or T_CO_URL.search(url) or FXTWITTER_URL.search(url))


def extract_status_url(url: str) -> str | None:
    """Palauttaa latauskelpoisen URL:n."""
    # Täysi x.com / twitter.com
    m = X_URL_PATTERN.search(url)
    if m:
        username, status_id = m.group(1), m.group(2)
        return f"https://x.com/{username}/status/{status_id}"

    # fxtwitter → normaloi x.com-osoitteeksi jos username on oikea
    m = FXTWITTER_URL.search(url)
    if m:
        username, status_id = m.group(1), m.group(2)
        if username != "i":  # "i" on placeholder
            return f"https://x.com/{username}/status/{status_id}"
        # Placeholder: palautetaan alkuperäinen, yt-dlp kokeilee
        return url

    # t.co-pikalinkki – yt-dlp seuraa redirectin
    if T_CO_URL.search(url):
        return url

    return None

def _check_non_retryable(error: Exception) -> NonRetryableError | None:
    msg = str(error)
    if X_NON_RETRYABLE.search(msg):
        return NonRetryableError(
            message=msg,
            user_facing="⚠️ X-postaus ei ole saatavilla (poistettu, yksityinen tai lasku suljettu).",
        )
    return None

# ============================================================
# LATAUS
# ============================================================

def _download_sync(url: str) -> VideoInfo | None:
    """Synchroninen lataus. Palauttaa VideoInfo-objektin."""
    tmpdir = tempfile.mkdtemp(prefix="x_")

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": os.path.join(tmpdir, "video.%(ext)s"),
        "noplaylist": True,
        "ffmpeg_location": _ffmpeg_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
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
        log.error("X-lataus epäonnistui: %s", e)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None

    files = [f for f in os.listdir(tmpdir) if f.endswith(".mp4")]
    if not files:
        files = [f for f in os.listdir(tmpdir) if f.lower().endswith((".jpg", ".jpeg", ".webp", ".gif"))]

    if not files:
        log.warning("X: Ei mediatiedostoa löytynyt")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None

    filepath = os.path.join(tmpdir, files[0])
    filename = f"x_video_{files[0]}"
    is_video = files[0].endswith(".mp4")

    import uuid
    unique_name = f"x_{uuid.uuid4().hex[:8]}_{files[0]}"
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

    # source_url: käytä yt-dlp:n web-page-URL:ia jos saatavilla (täysi x.com)
    url = (info_dict.get("webpage_url") or url) if info_dict else url

    # Poista URL:t titlestä ja descriptionista — source_url riittää
    title = re.sub(r"\s*[-–—]?\s*(?:https?://\S+|t\.co/\S+)", "", title).strip()
    description = re.sub(r"https?://\S+", "", description).strip()

    # Jos description tyhjeni, ei näytetä
    if not description:
        description = ""


    log.info("✅ X-lataus valmis: %s (%.1f MB)",
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


async def download_x(url: str) -> VideoInfo | None:
    """Lataa X-videon asynkisesti."""
    clean = extract_status_url(url)
    if not clean:
        log.warning("X: Ei status-URL:ää: %s", url[:80])
        return None

    log.info("🐦 X-lataus aloitettu: %s", clean)
    result = await asyncio.to_thread(_download_sync, clean)

    if result:
        log.info("✅ X: %s", result.filename)
    else:
        log.error("❌ X-lataus epäonnistui: %s", url[:80])

    return result
