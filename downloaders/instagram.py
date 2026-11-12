"""Instagram-videoiden ja kuvien lataus instaloaderilla."""
import os
import re
import asyncio
import tempfile
import shutil

import instaloader

from core.logging import log
from core.models import VideoInfo, NonRetryableError


DISCORD_FILE_LIMIT = 25 * 1024 * 1024  # 25 MB

# Yleinen selainprofiili – auttaa 401-virheisiin
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ============================================================
# URL-TUNNISTUS
# ============================================================

INSTAGRAM_PATTERNS = [
    r"https?://(?:www\.)?instagram\.com/reel/([A-Za-z0-9_-]+)",
    r"https?://(?:www\.)?instagram\.com/p/([A-Za-z0-9_-]+)",
    r"https?://(?:www\.)?instagram\.com/tv/([A-Za-z0-9_-]+)",
    r"https?://(?:www\.)?instagram\.com/reels/([A-Za-z0-9_-]+)",
]


def is_instagram(url: str) -> bool:
    return "instagram.com/" in url


def extract_shortcode(url: str) -> str | None:
    """Poimi shortcode (esim. Dedz4FutFAq) Instagram-URL:stä."""
    # Etsi path-segmentti joka sisältää validin shortcoden
    for pattern in INSTAGRAM_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return m.group(1)

    # Generinen: instagram.com/{type}/{shortcode}/?...
    m = re.search(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)

    return None
    
# ============================================================
# VIRHETARKISTUS
# ============================================================

IG_NON_RETRYABLE = re.compile(
    r"not found|"
    r"private account|"
    r"this account is private|"
    r"login required|"
    r"forbidden|"
    r"401",
    re.IGNORECASE,
)


def _check_non_retryable(error: Exception) -> NonRetryableError | None:
    msg = str(error)
    if IG_NON_RETRYABLE.search(msg):
        return NonRetryableError(
            message=msg,
            user_facing="⚠️ Instagram-postaus ei ole saatavilla (yksityinen tai poistettu).",
        )
    return None

# ============================================================
# LATAUS
# ============================================================

def _download_sync(shortcode: str, url: str) -> VideoInfo | None:
    """Synchroninen lataus. Palauttaa VideoInfo-objektin."""
    final_path = None
    try:
        with tempfile.TemporaryDirectory(prefix="ig_") as tmpdir:
            dirname_pattern = tmpdir.replace("{", "{{").replace("}", "}}")

            L = instaloader.Instaloader(
                dirname_pattern=dirname_pattern,
                download_pictures=True,           # esikatselukuva
                download_videos=True,             # Lataa video
                download_video_thumbnails=False,  # Ei videon pikkukuvia
                download_geotags=False,           # Ei paikkatietoja
                download_comments=False,          # Ei kommentteja
                save_metadata=False,              # Ei JSON-metadataa
            )

            # Yleinen selainprofiili – auttaa 401-virheisiin
            L.context.user_agent = USER_AGENT

            post = instaloader.Post.from_shortcode(L.context, shortcode)
            L.download_post(post, target=shortcode)

            # --- Metadata ---
            title = post.title or ""
            # owner voi puuttua tai olla None
            owner = getattr(post, 'owner', None)
            # uploader = f"@{post.owner.username}"
            uploader = f"@{owner.username}" if owner and hasattr(owner, 'username') and owner.username else ""
            description = post.caption or ""
            if description == title:
                description = ""

            # Poista kaikki paitsi halutut media-tiedostot
            allowed_ext = (".mp4", ".jpg", ".jpeg", ".png", ".webp")
            for root, _, files in os.walk(tmpdir):
                for name in files:
                    full_path = os.path.join(root, name)
                    if not name.lower().endswith(allowed_ext):
                        os.remove(full_path)

            # Etsi media-tiedostoja
            media_files = []
            for root, _, files in os.walk(tmpdir):
                for name in files:
                    if name.lower().endswith(allowed_ext):
                        media_files.append(os.path.join(root, name))

            if not media_files:
                log.warning("Instagram: Ei mediatiedostoja. Hakemistopuu: %s",
                            [os.path.join(r, f) for r, _, fs in os.walk(tmpdir) for f in fs])
                return None

            # Video ensin, sitten kuva
            videos = [p for p in media_files if p.lower().endswith(".mp4")]
            filepath = max(videos or media_files, key=os.path.getsize)
            filename = os.path.basename(filepath)
            ext = os.path.splitext(filename)[1]
            is_video = ext == ".mp4"

            with tempfile.NamedTemporaryFile(
                prefix=f"ig_{shortcode}_", suffix=ext, delete=False
            ) as output:
                final_path = output.name
            shutil.copyfile(filepath, final_path)

        log.info("✅ Instagram-lataus valmis: %s (%.1f MB)",
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
        if final_path and os.path.exists(final_path):
            os.unlink(final_path)
        raise
    except Exception as e:
        non_retryable = _check_non_retryable(e)
        if non_retryable:
            if final_path and os.path.exists(final_path):
                os.unlink(final_path)
            raise non_retryable from e
        if final_path and os.path.exists(final_path):
            os.unlink(final_path)
        log.error("Instagram: Lataus epäonnistui (shortcode: %s): %s", shortcode, e)
        return None


async def download_instagram(url: str) -> VideoInfo | None:
    """Lataa Instagram-videon tai kuvan asynkisesti."""
    shortcode = extract_shortcode(url)
    if not shortcode:
        log.warning("Instagram: Ei shortcodetta URL:stä: %s", url[:80])
        return None

    log.info("📱 Instagram-lataus aloitettu: shortcode=%s", shortcode)
    
    try:
        result = await asyncio.to_thread(_download_sync, shortcode, url)
        if result:
            log.info("✅ Instagram: %s", result.filename)
        return result
    except NonRetryableError:
        log.warning("🚫 Instagram: Ei saatavilla: %s", url[:80])
        raise

