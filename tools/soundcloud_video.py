"""Muodosta SoundCloud-kappaleesta kansikuvallinen MP4."""
import asyncio
import io
import os
import re
import subprocess
import tempfile
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps
from static_ffmpeg import run

from core.logging import log
from downloaders.base import finalize

_ARTWORK_URL = re.compile(r"https://[a-z0-9-]+\.sndcdn\.com/", re.IGNORECASE)
_MAX_ARTWORK_BYTES = 5 * 1024 * 1024
_FRAME_SIZE = 640
_INTRO_SECONDS = 5


async def _fetch_artwork(url: str) -> bytes | None:
    if not _ARTWORK_URL.match(url):
        return None

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.get(url, allow_redirects=False) as response:
            if response.status != 200:
                return None
            artwork = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                artwork.extend(chunk)
                if len(artwork) > _MAX_ARTWORK_BYTES:
                    return None
            return bytes(artwork)


def _font(size: int):
    for name in ("DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _draw_line(draw, text: str, y: int, size: int, fill: str) -> None:
    font = _font(size)
    text = " ".join(text.split())[:200]
    if draw.textlength(text, font=font) > _FRAME_SIZE - 64:
        while draw.textlength(text + "…", font=font) > _FRAME_SIZE - 64:
            text = text[:-1]
        text += "…"
    draw.text((_FRAME_SIZE // 2, y), text, font=font, fill=fill, anchor="mt")


def _render_video(
    audio_path: str, artwork: bytes, title: str, artist: str, file_limit: int
) -> str | None:
    with Image.open(io.BytesIO(artwork)) as image:
        if image.width * image.height > 16_000_000:
            return None
        cover = ImageOps.pad(
            ImageOps.exif_transpose(image).convert("RGB"),
            (_FRAME_SIZE, _FRAME_SIZE),
            color="#17171b",
        )

    intro = cover.copy()
    draw = ImageDraw.Draw(intro, "RGBA")
    draw.rectangle((0, 506, _FRAME_SIZE, _FRAME_SIZE), fill=(18, 18, 22, 235))
    _draw_line(draw, title or "SoundCloud", 528, 33, "#ffffff")
    _draw_line(draw, artist, 581, 23, "#ffad86")

    ffmpeg, _ = run.get_or_fetch_platform_executables_else_raise()
    with tempfile.TemporaryDirectory(prefix="soundcloud_video_") as directory:
        cover_path = Path(directory) / "cover.png"
        intro_path = Path(directory) / "intro.png"
        video_path = Path(directory) / "track.mp4"
        cover.save(cover_path)
        intro.save(intro_path)
        subprocess.run(
            [
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-framerate", "5", "-i", str(cover_path),
                "-i", str(intro_path), "-i", audio_path,
                "-filter_complex",
                f"[0:v][1:v]overlay=enable='lt(t,{_INTRO_SECONDS})'[video]",
                "-map", "[video]", "-map", "2:a:0", "-shortest",
                "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(video_path),
            ],
            check=True, capture_output=True, timeout=300,
        )
        if os.path.getsize(video_path) > file_limit:
            return None
        return finalize(str(video_path), "soundcloud")


async def make_soundcloud_video(
    audio_path: str, artwork_url: str, title: str, artist: str, file_limit: int
) -> str | None:
    try:
        artwork = await _fetch_artwork(artwork_url)
        if artwork:
            return await asyncio.to_thread(
                _render_video, audio_path, artwork, title, artist, file_limit
            )
    except (aiohttp.ClientError, OSError, ValueError, TimeoutError,
            subprocess.SubprocessError, Image.DecompressionBombError):
        log.exception("SoundCloud-kansikuvavideon luonti epäonnistui")
    return None
