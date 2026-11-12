"""YouTube-videoiden lataus ja Discordiin lähettäminen."""
import os
import re
import asyncio
import tempfile
from urllib.parse import urlparse, parse_qs

import yt_dlp
import static_ffmpeg
from static_ffmpeg import run

from core.logging import log
from core.models import VideoInfo, NonRetryableError

# ffmpeg-biit (kerran käynnistyksessä)
static_ffmpeg.add_paths(weak=True)
_ffmpeg_path, _ = run.get_or_fetch_platform_executables_else_raise()

MAX_RETRIES = 2

# Discordin tiedostoraja
DISCORD_FILE_LIMIT = 15 * 1024 * 1024  # 15 MB (Discord ilman Nitroa)
YOUTUBE_QUALITY_STEPS = (1080, 720, 480, 360, 240, 144)

# Virheet joita ei kannata yrittää uudelleen laadulla
NON_RETRYABLE_PATTERNS = re.compile(
    r"private video|"
    r"video unavailable|"
    r"age[-\s]restricted|"
    r"members only|"
    r"removed by (?:the uploader|copyright)|"
    r"not available|"
    r"this video is not available",
    re.IGNORECASE,
)


# ============================================================
# URL-TUNNISTUS
# ============================================================

YOUTUBE_PATTERNS = [
    r"https?://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}",
    r"https?://(?:www\.)?youtu\.be/[\w-]{11}",
    r"https?://(?:www\.)?youtube\.com/shorts/[\w-]{11}",
    r"https?://(?:www\.)?youtube\.com/embed/[\w-]{11}",
]


def is_youtube(url: str) -> bool:
    return any(re.search(p, url) for p in YOUTUBE_PATTERNS)


def extract_video_id(url: str) -> str | None:
    """Palauttaa 11 merkkisen video-id:n."""
    # youtu.be/VIDEOID
    m = re.search(r"youtu\.be/([\w-]{11})", url)
    if m:
        return m.group(1)
    # watch?v=VIDEOID
    m = re.search(r"watch\?.*v=([\w-]{11})", url)
    if m:
        return m.group(1)
    # shorts/VIDEOID  tai  embed/VIDEOID
    m = re.search(r"(?:shorts|embed)/([\w-]{11})", url)
    if m:
        return m.group(1)
    return None


def clean_url(url: str) -> str:
    """Siivoo URL:n minimimuotoon."""
    video_id = extract_video_id(url)
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return url


def clean_description(description: str) -> str:
    """Poistaa YouTube-kuvauksesta some-linkit ja markkinointitekstit."""
    if not description:
        return ""

    # Poista kokonaiset markkinointirivit
    description = re.sub(
        r"(?im)^.*(?:all my links|socials|subscribe and like|"
        r"follow me|follow us|check out my|link in bio).*$",
        "",
        description,
    )

    # Poista yleisimmät some-linkit, vaikka ne olisivat omalla rivillään
    description = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        description,
        flags=re.IGNORECASE,
    )

    # Poista markkinointifraasit myös muun tekstin sisältä
    description = re.sub(
        r"(?i)\bsubscribe and like for more(?:\s+\w+)*",
        "",
        description,
    )

    # Siivoa tyhjiksi jääneet linkkitekstit ja Markdown-merkit
    description = re.sub(
        r"(?im)^\s*(?:all my links|socials|links|follow me)\s*:?\s*$",
        "",
        description,
    )
    description = re.sub(r"[ \t]+", " ", description)
    description = re.sub(r"\n\s*\n+", "\n", description)

    return description.strip()


# ============================================================
# LATAUS
# ============================================================

def _build_opts(output_dir: str, max_height: int = 720) -> dict:
    return {
        "format": (
            f"bestvideo[height<={max_height}]+bestaudio/"
            f"best[height<={max_height}]"
        ),
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "ffmpeg_location": _ffmpeg_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegMetadata",
        }],
    }


def _download_sync(url: str, max_height: int = 1080) -> VideoInfo | None:
    """Synchroninen lataus. Palauttaa VideoInfo-objektin."""
    with tempfile.TemporaryDirectory(prefix="yt_") as tmpdir:
        opts = _build_opts(tmpdir, max_height=max_height)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as e:
            # Tarkista onko virhe peruutettava
            non_retryable = _check_non_retryable(e)
            if non_retryable:
                raise non_retryable from e
            raise

        # Etsi merge-attu .mp4 (yt-dlp nimeää sen video-id:llä)
        video_id = info.get("id", "")
        expected = os.path.join(tmpdir, f"{video_id}.mp4")
        if os.path.exists(expected):
            filepath = expected
        else:
            files = [f for f in os.listdir(tmpdir) if f.endswith(".mp4")]
            if not files:
                raise FileNotFoundError(f"Ei .mp4-tiedostoa hakemistossa {tmpdir}")
            filepath = os.path.join(tmpdir, files[0])

        # --- Metadata ---
        title = info.get("title", "")
        uploader = info.get("uploader") or info.get("channel") or ""
        description = clean_description(info.get("description", ""))

        # Siirra tiedosto pysyvään väliaikahakemistoon
        with tempfile.NamedTemporaryFile(prefix="yt_", suffix=".mp4", delete=False) as output:
            final_path = output.name
        try:
            os.replace(filepath, final_path)
        except Exception:
            if os.path.exists(final_path):
                os.unlink(final_path)
            raise

        return VideoInfo(
            filepath=final_path,
            filename=os.path.basename(final_path),
            title=title,
            uploader=uploader,
            description=description,
            source_url=url,
            is_video=True,
        )

def _check_non_retryable(error: Exception) -> NonRetryableError | None:
    """Palauttaa NonRetryableError jos virhe on peruutettava."""
    msg = str(error)
    if NON_RETRYABLE_PATTERNS.search(msg):
        return NonRetryableError(
            message=msg,
            user_facing="⚠️ Video ei ole saatavilla (yksityinen, poistettu tai ikärajoitettu).",
        )
    return None

async def download_video(url: str, max_height: int = 720) -> VideoInfo | None:
    """Lataa videon asynkisesti. Palauttaa VideoInfo:n tai None."""
    clean = clean_url(url)
    log.info("🎬 YouTube-lataus aloitettu (%sp): %s", max_height, clean)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = await asyncio.to_thread(_download_sync, clean, max_height=max_height)
            if result:
                size_mb = os.path.getsize(result.filepath) / (1024 * 1024)
                log.info("✅ Lataus valmis: %s (%.1f MB)", result.filename, size_mb)
            return result
        except NonRetryableError:
            # Älä logaa errorina – tämä on odotettu tilanne
            log.warning("🚫 YouTube: Video ei ole saatavilla: %s", clean)
            raise  # anna bot.py:n hoitaa
        except Exception as e:
            if attempt < MAX_RETRIES:
                log.warning("⚠️ Yritys %d/%d epäonnistui: %s – yritetään uudelleen...",
                           attempt, MAX_RETRIES, e)
                await asyncio.sleep(2 * attempt)
            else:
                log.error("❌ YouTube-lataus epäonnistui: %s", e)
                return None
    return None

