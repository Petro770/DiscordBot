"""Muodosta SoundCloud-kappaleesta kansikuvallinen MP4."""
import asyncio
import io
import os
import random
import re
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path
from threading import Timer
from time import monotonic

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps
from static_ffmpeg import run

from core.logging import log
from downloaders.base import finalize

_ARTWORK_URL = re.compile(
    r"https://(?:[a-z0-9-]+\.sndcdn\.com|cdn\.discordapp\.com|media\.discordapp\.net)/",
    re.IGNORECASE,
)
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
    ("lowpass=f=220", 3.4, 36, (255, 153, 82, 200), 2),
    ("highpass=f=220,lowpass=f=2500", 2.4, 56, (221, 148, 255, 220), 2),
    ("highpass=f=2500", 1.5, 76, (109, 225, 255, 255), 3),
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


def _title_overlay(title: str) -> tuple[Image.Image, str]:
    font = _font(33)
    text = " ".join(title.split()) or "SoundCloud"
    left, top, right, bottom = font.getbbox(text)
    width = right - left + 4
    image = Image.new("RGBA", (width, bottom - top + 4))
    ImageDraw.Draw(image).text((2 - left, 2 - top), text, font=font, fill="white")

    margin = 32
    travel = width - (_FRAME_SIZE - 2 * margin)
    if travel <= 0:
        return image, str((_FRAME_SIZE - width) // 2)
    return image, f"{margin}-{travel}*clip((t-0.5)/{_INTRO_SECONDS - 1},0,1)"


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
            mirrored = [(x, 2 * center - y) for x, y in reversed(points)]
            layer = Image.new("RGBA", frame.size)
            wave = ImageDraw.Draw(layer)
            wave.polygon(points + mirrored, fill=(*color[:3], 85))
            wave.line(points, fill=color, width=width)
            wave.line(mirrored, fill=color, width=width)
            frame.alpha_composite(layer)
        yield frame.tobytes()


def _encode_video(command: list[str], envelopes: tuple[array, ...], message_id: int | None) -> None:
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        command, stdin=subprocess.PIPE, stderr=errors, creationflags=_NO_CONSOLE,
    ) as ffmpeg:
        # Aikaraja koskee myös ruutujen syöttämistä putkeen.
        def stop_timed_out_encode():
            if ffmpeg.poll() is None:
                log.error("SoundCloud-video [%s]: FFmpeg-renderöinnin 300 s aikaraja", message_id)
                ffmpeg.kill()

        watchdog = Timer(300, stop_timed_out_encode)
        started = last_update = monotonic()
        frames_written = 0
        log.info("SoundCloud-video [%s]: FFmpeg käynnistyi (PID %d)", message_id, ffmpeg.pid)
        watchdog.start()
        try:
            with ffmpeg.stdin as frames:
                for frame in _wave_frames(envelopes):
                    frames.write(frame)
                    frames_written += 1
                    now = monotonic()
                    if now - last_update >= 15:
                        log.info(
                            "SoundCloud-video [%s]: FFmpegille syötetty %.1f s videota (kestänyt %.1f s)",
                            message_id, frames_written / _VIDEO_FPS, now - started,
                        )
                        last_update = now
            log.info("SoundCloud-video [%s]: ruudut syötetty, odotetaan MP4:n viimeistelyä", message_id)
        except BrokenPipeError:
            log.warning("SoundCloud-video [%s]: FFmpeg sulki ruutuputken", message_id)
        finally:
            returncode = ffmpeg.wait()
            watchdog.cancel()
        log.info(
            "SoundCloud-video [%s]: FFmpeg päättyi %.1f s jälkeen (koodi %d, %d ruutua)",
            message_id, monotonic() - started, returncode, frames_written,
        )
        if returncode:
            errors.seek(0)
            raise subprocess.CalledProcessError(returncode, command, stderr=errors.read())


def _fallback_cover() -> Image.Image:
    size = 800
    colors = [tuple(random.randint(32, 220) for _ in range(3)) for _ in range(5)]
    cover = Image.new("RGB", (size, size), colors[0])
    draw = ImageDraw.Draw(cover)
    for index, color in enumerate(colors[1:], start=1):
        offset = index * 180
        draw.polygon(
            [(offset - 370, 0), (offset, 0), (offset + 390, size), (offset - 10, size)],
            fill=color,
        )
    return cover


def _compress_for_upload(
    ffmpeg: str, source: Path, target: Path, duration: float, file_limit: int,
    message_id: int | None,
) -> bool:
    # Jätä tilaa MP4-säiliölle ja enkooderin bittivirtavaihtelulle.
    total_bitrate = int(file_limit * 8 * 0.90 / duration)
    audio_bitrate = min(128_000, max(48_000, total_bitrate // 2))
    video_bitrate = total_bitrate - audio_bitrate
    if video_bitrate < 20_000:
        log.warning("SoundCloud-video [%s]: kokoraja on liian pieni koko kappaleelle", message_id)
        return False

    width = 320 if video_bitrate < 90_000 else 480
    log.info(
        "SoundCloud-video [%s]: pakataan MP4 (%dx%d, video %d b/s, ääni %d b/s)",
        message_id, width, width, video_bitrate, audio_bitrate,
    )
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-vf", f"scale={width}:-2",
        "-c:v", "libx264", "-preset", "fast", "-b:v", str(video_bitrate),
        "-passlogfile", str(target.with_suffix(".pass")),
    ]
    started = monotonic()
    subprocess.run(
        command + ["-pass", "1", "-an", "-f", "null", os.devnull],
        check=True, capture_output=True, timeout=300, creationflags=_NO_CONSOLE,
    )
    subprocess.run(
        command + [
            "-pass", "2", "-map", "0:a:0", "-c:a", "aac", "-b:a", str(audio_bitrate),
            "-movflags", "+faststart", str(target),
        ],
        check=True, capture_output=True, timeout=300, creationflags=_NO_CONSOLE,
    )
    size = target.stat().st_size
    log.info(
        "SoundCloud-video [%s]: pakkaus valmis %.1f sekunnissa (%d tavua, raja %d)",
        message_id, monotonic() - started, size, file_limit,
    )
    return 0 < size <= file_limit


def _render_video(
    audio_path: str, artwork: Image.Image | None, title: str, artist: str, file_limit: int,
    message_id: int | None,
) -> str | None:
    cover = ImageOps.pad(
        artwork if artwork is not None else _fallback_cover(),
        (_FRAME_SIZE, _FRAME_SIZE),
        color="#17171b",
    )

    intro = cover.copy()
    draw = ImageDraw.Draw(intro, "RGBA")
    draw.rectangle((0, 0, _FRAME_SIZE, 111), fill=(18, 18, 22, 235))
    _draw_line(draw, artist, 71, 23, "#ffad86")
    title_image, title_x = _title_overlay(title)

    log.info("SoundCloud-video [%s]: haetaan FFmpeg ja analysoidaan taajuuskaistat", message_id)
    ffmpeg, _ = run.get_or_fetch_platform_executables_else_raise()
    started = monotonic()
    envelopes = _read_envelopes(ffmpeg, audio_path)
    duration = len(envelopes[0]) / _ENVELOPE_HZ
    log.info(
        "SoundCloud-video [%s]: analyysi valmis %.1f sekunnissa, äänen kesto %.1f s",
        message_id, monotonic() - started, duration,
    )
    with tempfile.TemporaryDirectory(prefix="soundcloud_video_") as directory:
        cover_path = Path(directory) / "cover.png"
        intro_path = Path(directory) / "intro.png"
        title_path = Path(directory) / "title.png"
        video_path = Path(directory) / "track.mp4"
        cover.save(cover_path)
        intro.save(intro_path)
        title_image.save(title_path)
        _encode_video(
            [
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-framerate", str(_VIDEO_FPS), "-i", str(cover_path),
                "-i", str(intro_path), "-i", audio_path, "-i", str(title_path),
                "-f", "rawvideo", "-pixel_format", "rgba",
                "-video_size", f"{_WAVE_WIDTH}x{_WAVE_HEIGHT}",
                "-framerate", str(_VIDEO_FPS), "-i", "pipe:0",
                "-filter_complex_threads", "1", "-filter_complex",
                f"[0:v][1:v]overlay=enable='lt(t,{_INTRO_SECONDS})'[intro];"
                f"[intro][3:v]overlay=x='{title_x}':y=22:enable='lt(t,{_INTRO_SECONDS})'[cover];"
                "[cover][4:v]overlay=x=24:y=380:eof_action=pass[video]",
                "-map", "[video]", "-map", "2:a:0", "-shortest",
                "-c:v", "libx264", "-preset", "fast", "-crf", "24",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(video_path),
            ],
            envelopes, message_id,
        )
        video_size = os.path.getsize(video_path)
        if video_size > file_limit:
            log.warning(
                "SoundCloud-video [%s]: MP4 ylittää tiedostorajan (%d > %d tavua)",
                message_id, video_size, file_limit,
            )
            compressed_path = video_path.with_name("track-compressed.mp4")
            if not _compress_for_upload(
                ffmpeg, video_path, compressed_path, duration, file_limit, message_id,
            ):
                return None
            video_path = compressed_path
            video_size = video_path.stat().st_size
        log.info("SoundCloud-video [%s]: MP4 valmis (%d tavua, raja %d)", message_id, video_size, file_limit)
        return finalize(str(video_path), "soundcloud")


def _decode_artwork(data: bytes) -> Image.Image | None:
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height <= 16_000_000:
            return ImageOps.exif_transpose(image).convert("RGB")
    return None


async def make_soundcloud_video(
    audio_path: str, artwork_url: str, title: str, artist: str, file_limit: int,
    *, avatar_url: str = "", message_id: int | None = None,
) -> str | None:
    cover = None
    # yt-dlp antaa SoundCloud-julkaisijan avatarin thumbnailina, jos kansikuva puuttuu.
    for source, url in (("SoundCloud-kuva", artwork_url), ("Discord-avatar", avatar_url)):
        if not url:
            continue
        log.info("SoundCloud-video [%s]: haetaan %s", message_id, source)
        try:
            artwork = await _fetch_artwork(url)
            if artwork:
                cover = await asyncio.to_thread(_decode_artwork, artwork)
        except (aiohttp.ClientError, OSError, ValueError, TimeoutError, Image.DecompressionBombError):
            log.debug("SoundCloud-video [%s]: kuvaa ei voitu käyttää", message_id, exc_info=True)
        if cover is not None:
            log.info("SoundCloud-video [%s]: käytetään lähdettä %s (%dx%d)", message_id, source, *cover.size)
            break
        log.info("SoundCloud-video [%s]: %s ei ollut käytettävissä", message_id, source)

    if cover is None:
        log.info("SoundCloud-video [%s]: piirretään varakuva", message_id)
    try:
        return await asyncio.to_thread(_render_video, audio_path, cover, title, artist, file_limit, message_id)
    except subprocess.CalledProcessError as error:
        details = (error.stderr or b"").decode(errors="replace")
        log.error("SoundCloud-video [%s]: FFmpeg-virhe (%s): %s", message_id, error.returncode, details[-1000:])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        log.exception("SoundCloud-video [%s]: luonti epäonnistui", message_id)
    return None
