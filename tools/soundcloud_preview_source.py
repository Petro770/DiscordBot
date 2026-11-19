"""Reusable input for rendering one SoundCloud preview frame."""
from array import array
from dataclasses import dataclass, replace
from io import BytesIO
import json
from math import exp
from zipfile import ZipFile

from PIL import Image

from tools.soundcloud_beats import estimate_downbeat_phase
from tools.soundcloud_video import (
    _compose_preview, _ENVELOPE_HZ, _FRAME_SIZE, _wave_frames, _wave_palette,
)
from tools.soundcloud_video_settings import SoundCloudVideoSettings


@dataclass
class SoundCloudPreviewSource:
    settings: SoundCloudVideoSettings
    envelopes: tuple
    beats: tuple
    cover: Image.Image
    intro: Image.Image
    title: Image.Image
    downbeat_phase: int | None = None

    @classmethod
    def from_archive(cls, path):
        with ZipFile(path) as archive:
            settings = SoundCloudVideoSettings.from_json(archive.read("settings.json"))
            images = []
            for name in ("cover.png", "intro.png", "title.png"):
                with Image.open(BytesIO(archive.read(name))) as image:
                    images.append(image.copy())
            beats = tuple(json.loads(archive.read("beats.json")))
            envelopes = []
            for index in range(settings.bands):
                band = array("f")
                band.frombytes(archive.read(f"band-{index}.bin"))
                envelopes.append(band)
            if not envelopes[0] or any(len(band) != len(envelopes[0]) for band in envelopes):
                raise ValueError("Esikatselun taajuuskaistat ovat virheellisiä.")
            try:
                phase = json.loads(archive.read("downbeat.json"))
            except KeyError:
                phase = estimate_downbeat_phase(envelopes[0], beats)
        return cls(settings, tuple(envelopes), beats, *images, downbeat_phase=phase)

    @classmethod
    def example(cls, settings=SoundCloudVideoSettings(intro_seconds=0)):
        beats = tuple(index / 2 for index in range(16))
        envelopes = tuple(
            array("f", (0.04 + 0.62 * exp(-falloff * ((i + offset) % 60) / 60)
                        for i in range(8 * _ENVELOPE_HZ)))
            for falloff, offset in (((13, 0), (7, 42), (17, 30))[i % 3]
                                    for i in range(settings.bands))
        )
        cover = Image.new("RGB", (_FRAME_SIZE, _FRAME_SIZE), "#252130")
        return cls(settings, envelopes, beats, cover, cover, Image.new("RGBA", (1, 1)), downbeat_phase=0)

    @property
    def duration(self):
        return len(self.envelopes[0]) / _ENVELOPE_HZ

    def frame(self, seconds, overrides):
        settings = replace(self.settings, **overrides)
        last_frame = (len(self.envelopes[0]) * settings.fps - 1) // _ENVELOPE_HZ
        index = min(last_frame, max(0, round(seconds * settings.fps)))
        palette = _wave_palette(self.cover, settings.bands)
        frame = next(_wave_frames(self.envelopes, settings, palette, self.beats, start_frame=index,
                                  downbeat_phase=self.downbeat_phase))
        return _compose_preview(frame, index / settings.fps, self.cover, self.intro, self.title,
                                settings.intro_seconds)
