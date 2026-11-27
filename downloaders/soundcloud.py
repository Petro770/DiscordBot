"""SoundCloud-kappaleiden lataus MP3-tiedostoiksi."""
import asyncio
import re
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
import yt_dlp

from core.logging import log
from tools.download_progress import report, download_hook
from core.models import NonRetryableError, VideoInfo
from downloaders.base import ffmpeg_executables, finalize


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


def _make_video(audio: Path, image: Path | None, output: Path, ffmpeg: str) -> None:
    picture = ["-loop", "1", "-i", str(image)] if image else [
        "-f", "lavfi", "-i", "color=c=black:s=720x720:r=1",
    ]
    subprocess.run([
        ffmpeg, "-y", *picture, "-i", str(audio),
        "-vf", "scale=720:720:force_original_aspect_ratio=decrease,pad=720:720:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-tune", "stillimage", "-r", "1", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(output),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _download_sync(url: str, as_video: bool = False, audio_kbps: int = 128) -> VideoInfo | None:
    with tempfile.TemporaryDirectory(prefix="soundcloud_") as directory:
        audio_path = Path(directory) / "track.mp3"
        report("prepare", "Varmistetaan FFmpeg ja haetaan kappaleen tiedot…")
        ffmpeg_path, _ = ffmpeg_executables()
        options = {
            "format": "bestaudio",
            "allowed_extractors": ["soundcloud"],
            "outtmpl": str(audio_path.with_suffix(".%(ext)s")),
            "ffmpeg_location": ffmpeg_path,
            "noplaylist": True,
            "quiet": True,
            "progress_hooks": [download_hook()],
            "postprocessor_hooks": [lambda data: report("audio", "Muunnetaan ladattua ääntä…")],
            "socket_timeout": 20,
            "writethumbnail": as_video,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(audio_kbps),
            }],
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True, ie_key="Soundcloud")
            if not info or not audio_path.is_file():
                return None
            filename = ydl.prepare_filename(info, outtmpl="%(title).150B.mp3")

        output_path = audio_path
        if as_video:
            from PIL import Image

            image_path = None
            for candidate in Path(directory).glob("track.*"):
                if candidate == audio_path:
                    continue
                try:
                    with Image.open(candidate) as image:
                        image_path = Path(directory) / "cover.png"
                        image.convert("RGB").save(image_path)
                    break
                except (OSError, ValueError):
                    continue
            output_path = Path(directory) / "track.mp4"
            _make_video(audio_path, image_path, output_path, ffmpeg_path)
            filename = str(Path(filename).with_suffix(".mp4"))

        return VideoInfo(
            filepath=finalize(str(output_path), "soundcloud"),
            filename=filename,
            title=info.get("title") or "",
            uploader=info.get("uploader") or "",
            source_url=url,
            is_video=as_video,
            artwork_url=info.get("thumbnail") or "",
        )


async def download_soundcloud(url: str, *, as_video: bool = False, audio_kbps: int = 128) -> VideoInfo | None:
    try:
        report("resolve", "Selvitetään SoundCloud-kappaleen linkkiä…")
        track_url = await _resolve_track(url)
        return await asyncio.to_thread(_download_sync, track_url, as_video, audio_kbps)
    except (aiohttp.ClientError, TimeoutError, yt_dlp.utils.DownloadError, OSError):
        log.exception("SoundCloud-lataus epäonnistui")
        return None
