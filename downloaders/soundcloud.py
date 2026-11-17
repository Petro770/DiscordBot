"""SoundCloud-kappaleiden lataus MP3-tiedostoiksi."""
import asyncio
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
import yt_dlp
from static_ffmpeg import run

from core.logging import log
from core.models import NonRetryableError, VideoInfo
from downloaders.base import finalize


_TRACK_URL = re.compile(
    r"https?://(?:(?:www|m)\.)?soundcloud\.com/[\w-]+/"
    r"(?!(?:tracks|albums|sets|reposts|likes|spotlight|comments)(?:/|[?#]|$))"
    r"[\w-]+(?:/s-[\w-]+)?/?(?:[?#][^\s]*)?",
    re.IGNORECASE,
)
_SHARE_URL = re.compile(
    r"https?://(?:on\.soundcloud\.com|soundcloud\.app\.goo\.gl|snd\.sc)"
    r"/[\w-]+/?(?:[?#][^\s]*)?",
    re.IGNORECASE,
)


def is_soundcloud(url: str) -> bool:
    return bool(_TRACK_URL.fullmatch(url) or _SHARE_URL.fullmatch(url))


async def _resolve_track(url: str) -> str:
    if _TRACK_URL.fullmatch(url):
        return url

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        for _ in range(3):
            if not _SHARE_URL.fullmatch(url):
                break
            async with session.get(url, allow_redirects=False) as response:
                location = response.headers.get("Location")
                if response.status not in (301, 302, 303, 307, 308) or not location:
                    break
                url = urljoin(url, location)
            if _TRACK_URL.fullmatch(url):
                return url

    raise NonRetryableError("⚠️ SoundCloud-jakolinkistä ei löytynyt yksittäistä kappaletta.")


def _download_sync(url: str) -> VideoInfo | None:
    with tempfile.TemporaryDirectory(prefix="soundcloud_") as directory:
        audio_path = Path(directory) / "track.mp3"
        ffmpeg_path, _ = run.get_or_fetch_platform_executables_else_raise()
        options = {
            "format": "bestaudio",
            "allowed_extractors": ["soundcloud"],
            "outtmpl": str(audio_path.with_suffix(".%(ext)s")),
            "ffmpeg_location": ffmpeg_path,
            "noplaylist": True,
            "quiet": True,
            "socket_timeout": 20,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }],
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True, ie_key="Soundcloud")
            if not info or not audio_path.is_file():
                return None
            filename = ydl.prepare_filename(info, outtmpl="%(title).150B.mp3")

        return VideoInfo(
            filepath=finalize(str(audio_path), "soundcloud"),
            filename=filename,
            title=info.get("title") or "",
            uploader=info.get("uploader") or "",
            source_url=url,
            is_video=False,
        )


async def download_soundcloud(url: str) -> VideoInfo | None:
    try:
        track_url = await _resolve_track(url)
        return await asyncio.to_thread(_download_sync, track_url)
    except (aiohttp.ClientError, TimeoutError, yt_dlp.utils.DownloadError, OSError):
        log.exception("SoundCloud-lataus epäonnistui")
        return None
