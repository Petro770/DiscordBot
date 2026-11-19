"""Muodosta SoundCloud-kappaleesta kansikuvallinen MP4."""
import asyncio
from bisect import bisect_left, bisect_right
import colorsys
import io
import math
import os
import random
import re
import subprocess
import sys
import tempfile
from array import array
from collections import OrderedDict
from pathlib import Path
from threading import Event, Timer
from time import monotonic

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
from static_ffmpeg import run

from core.logging import log
from tools.download_progress import report
from tools.soundcloud_beats import read_beat_grid
from tools.soundcloud_video_settings import SoundCloudVideoSettings
from downloaders.base import finalize

_ARTWORK_URL = re.compile(
    r"https://(?:[a-z0-9-]+\.sndcdn\.com|cdn\.discordapp\.com|media\.discordapp\.net)/",
    re.IGNORECASE,
)
_MAX_ARTWORK_BYTES = 5 * 1024 * 1024
_FRAME_SIZE = 640
_INTRO_SECONDS = 5
_ENVELOPE_HZ = 120
_WAVE_WIDTH = _FRAME_SIZE
_WAVE_HEIGHT = 112
_BEAT_FLOOR_HEIGHT = 216
_NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Taajuuskaista, aikaikkunan leveys (s), pystysijainti, väri ja viivan leveys.
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


def _title_overlay(title: str, intro_seconds: int = _INTRO_SECONDS) -> tuple[Image.Image, str]:
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
    return image, f"{margin}-{travel}*clip((t-0.5)/{max(0.1, intro_seconds - 1)},0,1)"


def _band_styles(settings):
    if settings.bands == 3:
        return _WAVE_BANDS
    edges = [60 * (16000 / 60) ** (i / settings.bands) for i in range(settings.bands + 1)]
    colors = ((255, 153, 82, 220), (221, 148, 255, 220), (109, 225, 255, 255))
    return tuple(
        (f"highpass=f={edges[i]:.2f},lowpass=f={edges[i + 1]:.2f}",
         3.4 - 1.9 * i / max(1, settings.bands - 1),
         round(_WAVE_HEIGHT * (i + 1) / (settings.bands + 1)), colors[i % 3], 2)
        for i in range(settings.bands)
    )


def _wave_palette(cover: Image.Image | None, count: int) -> tuple[tuple[int, int, int], ...]:
    """Choose a cover accent, keeping bass warm and treble gently cool."""
    if cover is None:
        base = (157, 176, 192)
    else:
        thumb = cover.convert("RGB").resize((64, 64), Image.Resampling.LANCZOS)
        quantized = thumb.quantize(colors=12)
        palette = quantized.getpalette()
        candidates = []
        for population, index in quantized.getcolors():
            rgb = tuple(palette[index * 3:index * 3 + 3])
            hue, saturation, value = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
            # Prefer a representative chromatic accent over black/white margins.
            weight = population * (0.15 + saturation) * (0.15 + min(value, 1 - value))
            candidates.append((weight, hue, saturation))
        _, hue, saturation = max(candidates)
        base = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, min(0.48, saturation * 0.7), 0.86))
    colors = []
    for index in range(count):
        position = index / max(1, count - 1)
        warm = max(0.0, 1 - 2 * position) * 0.65
        cool = max(0.0, 2 * position - 1) * 0.35
        colors.append(tuple(round(base[c] * (1 - warm - cool) + (224, 135, 133)[c] * warm
                                  + (139, 190, 207)[c] * cool) for c in range(3)))
    return tuple(colors)


def _wave_alpha(level: float, peak: float) -> int:
    # Retain a faint baseline during silence; avoid boosting quiet bands to full opacity.
    strength = min(1.0, max(0.0, level) / max(peak, 0.02))
    return min(255, round(1.30 * (28 + 207 * strength ** 0.50)))


def _read_envelopes(ffmpeg: str, audio_path: str, settings=SoundCloudVideoSettings()) -> tuple[array, ...]:
    count = settings.bands
    filters = [f"[0:a]aformat=channel_layouts=mono,asplit={count}" + "".join(f"[b{i}]" for i in range(count))]
    for index, (band_filter, *_style) in enumerate(_band_styles(settings)):
        filters.append(
            f"[b{index}]{band_filter},aeval=abs(val(0)):c=mono,"
            f"lowpass=f={min(15, settings.fps * 0.3):g},aresample={_ENVELOPE_HZ}:ochl=mono[e{index}]"
        )
    filters.append(
        # Serialize mono envelopes in band order. Joining them as audio channels
        # requires named speaker layouts (9c, 10c, ... are not generally valid).
        "".join(f"[e{i}]" for i in range(count))
        + f"concat=n={count}:v=0:a=1[envelopes]"
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
    if len(samples) % count:
        raise ValueError("Taajuuskaistojen analyysi tuotti eripituiset kaistat.")
    band_length = len(samples) // count
    return tuple(samples[index * band_length:(index + 1) * band_length] for index in range(count))


def _envelope_at(band: array, position: float) -> float:
    """Interpolate sub-sample motion, holding the edge instead of flashing to zero."""
    if not band:
        return 0.0
    position = min(max(position, 0.0), len(band) - 1)
    index = int(position)
    fraction = position - index
    return max(0.0, band[index] * (1 - fraction) + band[min(index + 1, len(band) - 1)] * fraction)


def _wave_centers(styles, settings):
    """Reserve room above bass for its full amplitude, stroke and antialiasing."""
    centers = [style[2] for style in styles]
    margin = settings.wave_line_width / 2 + 3
    top = max(min(centers), settings.wave_amplitude + margin)
    bottom = min(max(centers), _WAVE_HEIGHT - 1 - margin)
    if len(centers) == 1:
        return [min(top, _WAVE_HEIGHT - 1 - margin)]
    original_top, original_bottom = min(centers), max(centers)
    return [top + (center - original_top) * (bottom - top) / (original_bottom - original_top)
            for center in centers]


class _WaveStrip:
    """Draw each time slice once; retain at most three small tiles per band."""

    TILE_WIDTH = 1024
    CACHE_TILES = 3

    def __init__(self, band, scale, window, color, peak, settings):
        self.band, self.scale, self.color, self.peak = band, scale, color, peak
        self.pixels_per_sample = (_WAVE_WIDTH - 1) / (window * _ENVELOPE_HZ)
        self.factor = max(2, math.ceil(settings.resolution / _FRAME_SIZE))
        self.line_width = settings.wave_line_width
        self.margin = math.ceil(self.line_width / 2 + 3)
        self.amplitude = settings.wave_amplitude
        self.height = self.amplitude + 2 * self.margin + 1
        self.tiles = OrderedDict()
        self.source_key = None
        self.source = None

    def _tile(self, index):
        if index in self.tiles:
            self.tiles.move_to_end(index)
            return self.tiles[index]
        factor = self.factor
        padding = self.margin
        start = index * self.TILE_WIDTH
        image = Image.new("RGBA", ((self.TILE_WIDTH + 2 * padding) * factor, self.height * factor))
        draw = ImageDraw.Draw(image)
        # Align segments globally and overlap tiles so joins have no visible seams.
        first = math.floor((start - padding) / 2) * 2
        last = start + self.TILE_WIDTH + padding + 2
        previous = None
        previous_level = None
        for x in range(first, last + 1, 2):
            level = _envelope_at(self.band, x / self.pixels_per_sample)
            point = ((x - start + padding) * factor,
                     (self.margin + self.amplitude - level * self.scale) * factor)
            if previous is not None:
                alpha = _wave_alpha((previous_level + level) / 2, self.peak)
                draw.line((previous, point), fill=(*self.color, alpha), width=self.line_width * factor)
            previous, previous_level = point, level
        image = image.resize((self.TILE_WIDTH + 2 * padding, self.height), Image.Resampling.LANCZOS)
        tile = image.crop((padding, 0, padding + self.TILE_WIDTH, self.height)).convert("RGBa")
        self.tiles[index] = tile
        while len(self.tiles) > self.CACHE_TILES:
            self.tiles.popitem(last=False)
        return tile

    def frame(self, sample_position):
        left = sample_position * self.pixels_per_sample - _WAVE_WIDTH / 2
        # Extra pixels allow subpixel scrolling at a tile boundary.
        first = math.floor((left - 2) / self.TILE_WIDTH)
        last = math.floor((left + _WAVE_WIDTH + 2) / self.TILE_WIDTH)
        if self.source_key != (first, last):
            # Keep premultiplied alpha so Pillow does not reconvert an entire
            # wide source strip for every tiny fractional scroll.
            source = Image.new("RGBa", ((last - first + 1) * self.TILE_WIDTH, self.height))
            for index in range(first, last + 1):
                source.paste(self._tile(index), ((index - first) * self.TILE_WIDTH, 0))
            self.source, self.source_key = source, (first, last)
        offset = left - first * self.TILE_WIDTH
        integer = math.floor(offset)
        fraction = offset - integer
        view = self.source.crop((integer, 0, integer + _WAVE_WIDTH, self.height))
        if fraction > 1e-9:
            adjacent = self.source.crop((integer + 1, 0, integer + 1 + _WAVE_WIDTH, self.height))
            # Only horizontal motion is needed: blending two adjacent crops is
            # equivalent to bilinear translation without a general affine warp.
            view = Image.blend(view, adjacent, fraction)
        return view.convert("RGBA")



def _wave_frames(envelopes: tuple[array, ...], settings=SoundCloudVideoSettings(), palette=None, beat_times=()):
    styles = _band_styles(settings)
    centers = _wave_centers(styles, settings)
    palette = palette or _wave_palette(None, len(envelopes))
    maxima = [max(band, default=0) for band in envelopes]
    peak = max(maxima, default=0.02)
    strips = [
        _WaveStrip(band, settings.wave_amplitude / max(maximum, 0.02),
                   style[1] * settings.wave_window_percent / 100, color, peak, settings)
        for band, maximum, style, color in zip(envelopes, maxima, styles, palette)
    ]
    # Prepare invariant background and edge fade just once per render.
    overlay_height = _BEAT_FLOOR_HEIGHT if beat_times else _WAVE_HEIGHT
    background = Image.new("RGBA", (_WAVE_WIDTH, overlay_height))
    if settings.wave_background:
        ImageDraw.Draw(background).rounded_rectangle(
            (0, 0, _WAVE_WIDTH - 1, _WAVE_HEIGHT - 1), radius=16,
            fill=(18, 18, 22, settings.wave_opacity),
        )
    edge_width = _WAVE_WIDTH * 0.10
    edge_alpha = []
    for x in range(_WAVE_WIDTH):
        amount = min(1.0, min(x, _WAVE_WIDTH - 1 - x) / edge_width)
        edge_alpha.append(round(255 * amount * amount * (3 - 2 * amount)))
    edge_mask = Image.new("L", (_WAVE_WIDTH, 1))
    edge_mask.putdata(edge_alpha)
    edge_mask = edge_mask.resize(background.size)
    floor = _beat_floor(palette[0]) if beat_times else None
    frame_count = (len(envelopes[0]) * settings.fps + _ENVELOPE_HZ - 1) // _ENVELOPE_HZ
    for frame_index in range(frame_count):
        now = frame_index * _ENVELOPE_HZ / settings.fps
        frame = background.copy()
        if floor is not None:
            floor_frame = floor.copy()
            _draw_beat_sweep(floor_frame, beat_times, frame_index / settings.fps, palette[0])
            frame.alpha_composite(floor_frame)
        for strip, center in zip(strips, centers):
            frame.alpha_composite(strip.frame(now), (0, round(center - strip.amplitude - strip.margin)))
        frame.putalpha(ImageChops.multiply(frame.getchannel("A"), edge_mask))
        yield frame.tobytes()


def _floor_projection(depth: float) -> tuple[float, float]:
    """Return the row's y position and half-width at a projected depth."""
    horizon = _WAVE_HEIGHT - 13
    y = horizon + depth * (_BEAT_FLOOR_HEIGHT - 1 - horizon)
    half_width = 28 + depth * (_WAVE_WIDTH / 2 - 28)
    return y, half_width


def _beat_floor(color: tuple[int, int, int]) -> Image.Image:
    floor = Image.new("RGBA", (_WAVE_WIDTH, _BEAT_FLOOR_HEIGHT))
    draw = ImageDraw.Draw(floor)
    center = _WAVE_WIDTH / 2
    for step in range(12):
        start = step / 12
        end = (step + 1) / 12
        y1, width1 = _floor_projection(start)
        y2, width2 = _floor_projection(end)
        opacity = round(76 * math.sin(math.pi * (start + end) / 2))
        for rail in range(-4, 5):
            draw.line((center + width1 * rail / 4, y1, center + width2 * rail / 4, y2),
                      fill=(*color, opacity))
    for depth in (0.12, 0.27, 0.47, 0.72, 0.95):
        y, half_width = _floor_projection(depth)
        opacity = round(52 * math.sin(math.pi * depth))
        draw.line((center - half_width, y, center + half_width, y), fill=(*color, opacity))
    return floor


def _draw_beat_sweep(
    floor: Image.Image, beat_times: tuple[float, ...], now: float, color: tuple[int, int, int],
) -> None:
    half_travel = 0.85
    first = bisect_left(beat_times, now - half_travel)
    last = bisect_right(beat_times, now + half_travel)
    draw = ImageDraw.Draw(floor)
    center = _WAVE_WIDTH / 2
    horizon_y, horizon_width = _floor_projection(0.08)
    foreground_y, foreground_width = _floor_projection(0.95)
    highlight = tuple(round((channel + 255) / 2) for channel in color)
    for beat in beat_times[first:last]:
        age = now - beat
        # Translate in floor space. The wider foreground moves more pixels per
        # frame than the horizon, and the line crosses center exactly on the beat.
        position = -age / half_travel
        pulse = max(0, 1 - abs(age) / 0.12)
        fade = min(1, 4 * (1 - abs(position)))
        alpha = round(fade * (118 + 137 * pulse))
        if alpha:
            draw.line(
                (center + position * horizon_width, horizon_y,
                 center + position * foreground_width, foreground_y),
                fill=(*(highlight if pulse else color), alpha),
                width=2 + round(2 * pulse),
            )


def _encode_video(command: list[str], envelopes: tuple[array, ...], message_id: int | None, settings=SoundCloudVideoSettings(), palette=None, beat_times=()) -> None:
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        command, stdin=subprocess.PIPE, stderr=errors, creationflags=_NO_CONSOLE,
    ) as ffmpeg:
        # Timeout measures lack of progress, not the total song render duration.
        stopped = Event()
        last_activity = monotonic()

        def stop_timed_out_encode():
            nonlocal watchdog
            if stopped.is_set() or ffmpeg.poll() is not None:
                return
            remaining = settings.encode_timeout - (monotonic() - last_activity)
            if remaining <= 0:
                log.error("SoundCloud-video [%s]: FFmpeg ei edistynyt %d sekuntiin", message_id, settings.encode_timeout)
                ffmpeg.kill()
            else:
                watchdog = Timer(remaining, stop_timed_out_encode)
                watchdog.daemon = True
                watchdog.start()

        watchdog = Timer(settings.encode_timeout, stop_timed_out_encode)
        watchdog.daemon = True
        started = last_update = monotonic()
        last_progress = started
        total_frames = (len(envelopes[0]) * settings.fps + _ENVELOPE_HZ - 1) // _ENVELOPE_HZ
        report("render", "Muodostetaan aaltomuotovideota…", 0)
        frames_written = 0
        log.info("SoundCloud-video [%s]: FFmpeg käynnistyi (PID %d)", message_id, ffmpeg.pid)
        watchdog.start()
        try:
            with ffmpeg.stdin as frames:
                for frame in _wave_frames(envelopes, settings, palette, beat_times):
                    frames.write(frame)
                    last_activity = monotonic()
                    frames_written += 1
                    now = monotonic()
                    if now - last_progress >= 0.5:
                        speed = frames_written / max(now - started, 0.001)
                        report("render", f"{frames_written}/{total_frames} ruutua · {speed:.1f} ruutua/s",
                               min(100, frames_written * 100 / max(total_frames, 1)),
                               eta=max(0, total_frames - frames_written) / speed)
                        last_progress = now
                    if now - last_update >= 15:
                        log.info(
                            "SoundCloud-video [%s]: FFmpegille syötetty %.1f s videota (kestänyt %.1f s)",
                            message_id, frames_written / settings.fps, now - started,
                        )
                        last_update = now
            report("finalize", "Ruudut valmiit, odotetaan FFmpegin viimeistelyä…")
            log.info("SoundCloud-video [%s]: ruudut syötetty, odotetaan MP4:n viimeistelyä", message_id)
        except BrokenPipeError:
            log.warning("SoundCloud-video [%s]: FFmpeg sulki ruutuputken", message_id)
        finally:
            try:
                returncode = ffmpeg.wait()
            finally:
                stopped.set()
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
    message_id: int | None, settings=SoundCloudVideoSettings(),
) -> bool:
    # Jätä tilaa MP4-säiliölle ja enkooderin bittivirtavaihtelulle.
    total_bitrate = int(file_limit * 8 * 0.90 / duration)
    audio_bitrate = min(settings.audio_kbps * 1000, max(48_000, total_bitrate // 2))
    video_bitrate = total_bitrate - audio_bitrate
    if video_bitrate < 20_000:
        log.warning("SoundCloud-video [%s]: kokoraja on liian pieni koko kappaleelle", message_id)
        return False

    width = min(settings.resolution, 320 if video_bitrate < 90_000 else 480)
    log.info(
        "SoundCloud-video [%s]: pakataan MP4 (%dx%d, video %d b/s, ääni %d b/s)",
        message_id, width, width, video_bitrate, audio_bitrate,
    )
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-vf", f"scale={width}:-2",
        "-c:v", "libx264", "-preset", settings.preset, "-b:v", str(video_bitrate),
        "-passlogfile", str(target.with_suffix(".pass")),
    ]
    started = monotonic()
    report("compress", "Kokorajan pakkaus: ensimmäinen kierros…")
    subprocess.run(
        command + ["-pass", "1", "-an", "-f", "null", os.devnull],
        check=True, capture_output=True, timeout=settings.encode_timeout, creationflags=_NO_CONSOLE,
    )
    report("compress", "Kokorajan pakkaus: toinen kierros…")
    subprocess.run(
        command + [
            "-pass", "2", "-map", "0:a:0", "-c:a", "aac", "-b:a", str(audio_bitrate),
            "-movflags", "+faststart", str(target),
        ],
        check=True, capture_output=True, timeout=settings.encode_timeout, creationflags=_NO_CONSOLE,
    )
    size = target.stat().st_size
    log.info(
        "SoundCloud-video [%s]: pakkaus valmis %.1f sekunnissa (%d tavua, raja %d)",
        message_id, monotonic() - started, size, file_limit,
    )
    return 0 < size <= file_limit


def _render_video(
    audio_path: str, artwork: Image.Image | None, title: str, artist: str, file_limit: int,
    message_id: int | None, settings=SoundCloudVideoSettings(),
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
    title_image, title_x = _title_overlay(title, settings.intro_seconds)

    log.info("SoundCloud-video [%s]: haetaan FFmpeg ja analysoidaan taajuuskaistat", message_id)
    ffmpeg, _ = run.get_or_fetch_platform_executables_else_raise()
    started = monotonic()
    report("analysis", f"Analysoidaan {settings.bands} taajuuskaistaa…")
    envelopes = _read_envelopes(ffmpeg, audio_path, settings)
    duration = len(envelopes[0]) / _ENVELOPE_HZ
    report("analysis", "Tunnistetaan kappaleen tempoa…")
    try:
        beat_grid = read_beat_grid(ffmpeg, audio_path)
    except (OSError, ValueError, subprocess.SubprocessError):
        log.warning("SoundCloud-video [%s]: tempoanalyysi epäonnistui", message_id, exc_info=True)
        beat_grid = None
    if beat_grid:
        log.info("SoundCloud-video [%s]: tempo %.1f BPM (%.2f BPS)",
                 message_id, beat_grid.bpm, beat_grid.bpm / 60)
        report("analysis", f"Tempo {beat_grid.bpm:.1f} BPM ({beat_grid.bpm / 60:.2f} BPS)")
    log.info(
        "SoundCloud-video [%s]: analyysi valmis %.1f sekunnissa, äänen kesto %.1f s",
        message_id, monotonic() - started, duration,
    )
    beat_times = beat_grid.seconds if beat_grid else ()
    overlay_height = _BEAT_FLOOR_HEIGHT if beat_times else _WAVE_HEIGHT
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
                "-loop", "1", "-framerate", str(settings.fps), "-i", str(cover_path),
                "-i", str(intro_path), "-i", audio_path, "-i", str(title_path),
                "-f", "rawvideo", "-pixel_format", "rgba",
                "-video_size", f"{_WAVE_WIDTH}x{overlay_height}",
                "-framerate", str(settings.fps), "-i", "pipe:0",
                "-filter_complex_threads", "1", "-filter_complex",
                f"[0:v][1:v]overlay=enable='lt(t,{settings.intro_seconds})'[intro];"
                f"[intro][3:v]overlay=x='{title_x}':y=22:enable='lt(t,{settings.intro_seconds})'[cover];"
                f"[cover][4:v]overlay=x=0:y=380:eof_action=pass,scale={settings.resolution}:{settings.resolution}[video]",
                "-map", "[video]", "-map", "2:a:0", "-shortest", "-t", str(duration),
                "-c:v", "libx264", "-preset", settings.preset, "-crf", str(settings.crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", f"{settings.audio_kbps}k",
                "-movflags", "+faststart", str(video_path),
            ],
            envelopes, message_id, settings, _wave_palette(cover, settings.bands),
            beat_times,
        )
        video_size = os.path.getsize(video_path)
        if video_size > file_limit:
            if not settings.auto_compress:
                raise ValueError("Video ylittää kokorajan. Ota automaattinen pakkaus käyttöön tai pienennä laatua.")
            log.warning(
                "SoundCloud-video [%s]: MP4 ylittää tiedostorajan (%d > %d tavua)",
                message_id, video_size, file_limit,
            )
            compressed_path = video_path.with_name("track-compressed.mp4")
            if not _compress_for_upload(
                ffmpeg, video_path, compressed_path, duration, file_limit, message_id, settings,
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
    settings: SoundCloudVideoSettings | None = None,
) -> str | None:
    report("artwork", "Haetaan videon kansikuvaa…")
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
        return await asyncio.to_thread(_render_video, audio_path, cover, title, artist, file_limit, message_id, settings or SoundCloudVideoSettings())
    except subprocess.CalledProcessError as error:
        details = (error.stderr or b"").decode(errors="replace")
        log.error("SoundCloud-video [%s]: FFmpeg-virhe (%s): %s", message_id, error.returncode, details[-1000:])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        log.exception("SoundCloud-video [%s]: luonti epäonnistui", message_id)
    return None
