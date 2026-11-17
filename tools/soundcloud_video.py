"""Muodosta SoundCloud-kappaleesta kansikuvallinen MP4."""
import asyncio
import io
import os
import re
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path
from threading import Timer

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps
from static_ffmpeg import run

from core.logging import log
from downloaders.base import finalize

_ARTWORK_URL = re.compile(r"https://[a-z0-9-]+\.sndcdn\.com/", re.IGNORECASE)
_MAX_ARTWORK_BYTES = 5 * 1024 * 1024
_FRAME_SIZE = 640
_INTRO_SECONDS = 5
_VIDEO_FPS = 15
_ENVELOPE_HZ = 120
_WAVE_WIDTH = 592
_WAVE_HEIGHT = 112
_NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Taajuuskaista, näkyvä historia (s), pystysijainti, väri ja viivan leveys.
_WAVE_BANDS = (
    ("highpass=f=2500", 3.4, 36, (109, 225, 255, 200), 2),
    ("highpass=f=220,lowpass=f=2500", 2.4, 56, (221, 148, 255, 220), 2),
    ("lowpass=f=220", 1.5, 76, (255, 153, 82, 255), 3),
)


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


def _read_envelopes(ffmpeg: str, audio_path: str) -> tuple[array, ...]:
    filters = ["[0:a]aformat=channel_layouts=mono,asplit=3[b0][b1][b2]"]
    for index, (band_filter, *_style) in enumerate(_WAVE_BANDS):
        filters.append(
            f"[b{index}]{band_filter},aeval=abs(val(0)):c=mono,"
            f"lowpass=f=15,aresample={_ENVELOPE_HZ}:ochl=mono[e{index}]"
        )
    filters.append(
        "[e0][e1][e2]join=inputs=3:channel_layout=3.0:"
        "map=0.0-FL|1.0-FR|2.0-FC[envelopes]"
    )
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-loglevel", "error", "-i", audio_path,
         "-filter_complex", ";".join(filters), "-map", "[envelopes]", "-f", "f32le", "pipe:1"],
        check=True, capture_output=True, timeout=120, creationflags=_NO_CONSOLE,
    )
    samples = array("f")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    return tuple(samples[index::3] for index in range(3))


def _wave_frames(envelopes: tuple[array, ...]):
    scales = [32 / max(max(band, default=0), 0.02) for band in envelopes]
    samples_per_frame = _ENVELOPE_HZ // _VIDEO_FPS
    for now in range(0, len(envelopes[0]), samples_per_frame):
        frame = Image.new("RGBA", (_WAVE_WIDTH, _WAVE_HEIGHT))
        draw = ImageDraw.Draw(frame)
        draw.rounded_rectangle(
            (0, 0, _WAVE_WIDTH - 1, _WAVE_HEIGHT - 1), radius=16, fill=(18, 18, 22, 165)
        )
        for band, scale, style in zip(envelopes, scales, _WAVE_BANDS):
            _, history, center, color, width = style
            points = []
            for x in range(12, _WAVE_WIDTH - 11, 4):
                age = (_WAVE_WIDTH - 12 - x) / (_WAVE_WIDTH - 24) * history
                index = now - round(age * _ENVELOPE_HZ)
                height = max(0, band[index]) * scale if index >= 0 else 0
                points.append((x, center - round(height)))
            draw.line(points, fill=color, width=width)
            draw.line([(x, 2 * center - y) for x, y in points], fill=color, width=width)
        yield frame.tobytes()


def _encode_video(command: list[str], envelopes: tuple[array, ...]) -> None:
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        command, stdin=subprocess.PIPE, stderr=errors, creationflags=_NO_CONSOLE,
    ) as ffmpeg:
        # Aikaraja koskee myös ruutujen syöttämistä putkeen.
        watchdog = Timer(300, ffmpeg.kill)
        watchdog.start()
        try:
            with ffmpeg.stdin as frames:
                for frame in _wave_frames(envelopes):
                    frames.write(frame)
        except BrokenPipeError:
            pass
        finally:
            returncode = ffmpeg.wait()
            watchdog.cancel()
        if returncode:
            errors.seek(0)
            raise subprocess.CalledProcessError(returncode, command, stderr=errors.read())


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
    envelopes = _read_envelopes(ffmpeg, audio_path)
    with tempfile.TemporaryDirectory(prefix="soundcloud_video_") as directory:
        cover_path = Path(directory) / "cover.png"
        intro_path = Path(directory) / "intro.png"
        video_path = Path(directory) / "track.mp4"
        cover.save(cover_path)
        intro.save(intro_path)
        _encode_video(
            [
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-framerate", str(_VIDEO_FPS), "-i", str(cover_path),
                "-i", str(intro_path), "-i", audio_path,
                "-f", "rawvideo", "-pixel_format", "rgba",
                "-video_size", f"{_WAVE_WIDTH}x{_WAVE_HEIGHT}",
                "-framerate", str(_VIDEO_FPS), "-i", "pipe:0",
                "-filter_complex_threads", "1", "-filter_complex",
                f"[0:v][1:v]overlay=enable='lt(t,{_INTRO_SECONDS})'[cover];"
                "[cover][3:v]overlay=x=24:y=380:eof_action=pass[video]",
                "-map", "[video]", "-map", "2:a:0", "-shortest",
                "-c:v", "libx264", "-preset", "fast", "-crf", "24",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(video_path),
            ],
            envelopes,
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
