import tempfile
import unittest
import wave
from array import array
from math import exp, pi, sin
from pathlib import Path
from shutil import which

from PIL import Image, ImageChops

from tools.soundcloud_preview_source import SoundCloudPreviewSource
from tools.soundcloud_beats import estimate_beat_grid, read_beat_grid
from tools.soundcloud_video import _BEAT_FLOOR_HEIGHT, _WAVE_HEIGHT, _draw_beat_sweep, _wave_frames
from tools.soundcloud_video_settings import SoundCloudVideoSettings


class SoundCloudBeatTests(unittest.TestCase):
    def test_silence_and_steady_tone_have_no_grid(self):
        for level in (0, 0.2):
            self.assertIsNone(estimate_beat_grid(array("f", [level]) * 1200))

    @unittest.skipUnless(which("ffmpeg"), "FFmpeg is required for file analysis")
    def test_reads_tempo_and_phase_from_audio_file(self):
        sample_rate = 8000
        for bpm in (95, 120, 174):
            with self.subTest(bpm=bpm), tempfile.TemporaryDirectory() as directory:
                phase = 0.23
                period = 60 / bpm
                samples = array("h")
                for index in range(12 * sample_rate):
                    time = index / sample_rate - phase
                    age = time % period
                    kick = exp(-age * 48) * sin(2 * pi * 80 * age) if time >= 0 else 0
                    samples.append(round(20000 * kick))
                path = Path(directory) / "track.wav"
                with wave.open(str(path), "wb") as audio:
                    audio.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
                    audio.writeframes(samples.tobytes())
                grid = read_beat_grid(which("ffmpeg"), str(path))
                self.assertIsNotNone(grid)
                self.assertAlmostEqual(grid.bpm, bpm, delta=0.5)
                self.assertAlmostEqual(grid.seconds[0], phase, delta=0.035)
                self.assertAlmostEqual(grid.seconds[12], phase + 12 * period, delta=0.045)

    def test_sweep_moves_right_to_left_faster_in_the_foreground(self):
        positions = []
        peaks = []
        for now in (0.5, 1.0, 1.5):
            floor = Image.new("RGBA", (640, _BEAT_FLOOR_HEIGHT))
            _draw_beat_sweep(floor, (1.0,), now, (220, 150, 110),
                             SoundCloudVideoSettings(beat_floor_accent_every_four=False))
            alpha = floor.getchannel("A")
            positions.append([alpha.crop((0, y, 640, y + 1)).getbbox()[0] for y in (40, 120)])
            peaks.append(alpha.getextrema()[1])

        right, center, left = positions
        for depth in range(2):
            self.assertGreater(right[depth], center[depth])
            self.assertGreater(center[depth], left[depth])
            self.assertAlmostEqual(center[depth], 320, delta=2)
        self.assertGreater(right[1] - left[1], right[0] - left[0])
        self.assertGreater(peaks[1], max(peaks[0], peaks[2]))

    def test_frames_reserve_floor_space_when_a_beat_grid_exists(self):
        envelope = (array("f", [0.1]) * 120,)
        settings = SoundCloudVideoSettings(bands=1)
        for beats, height in (((), _WAVE_HEIGHT), ((0.5,), _BEAT_FLOOR_HEIGHT)):
            frame = next(_wave_frames(envelope, settings, beat_times=beats))
            self.assertEqual(len(frame), 640 * height * 4)

    def test_no_static_grid_when_no_beats_are_visible(self):
        envelope = (array("f", [0.1]) * 120,)
        settings = SoundCloudVideoSettings(bands=1)
        waveform = next(_wave_frames(envelope, settings))
        frame = next(_wave_frames(envelope, settings, beat_times=(2.0,)))
        self.assertEqual(frame[:len(waveform)], waveform)
        self.assertFalse(any(frame[len(waveform):]))

    def test_preview_applies_floor_settings_at_the_same_timestamp(self):
        source = SoundCloudPreviewSource.example()
        original = source.frame(1.0, {})
        adjusted = source.frame(1.0, {
            "beat_floor_x_offset": 40,
            "beat_floor_y_offset": -95,
            "beat_floor_height": 75,
        })
        without_floor = source.frame(1.0, {"beat_floor_enabled": False})
        self.assertIsNotNone(ImageChops.difference(original, adjusted).getbbox())
        self.assertIsNotNone(ImageChops.difference(original, without_floor).getbbox())

    def test_wide_horizon_and_height_change_the_projected_endpoints(self):
        near_edge = []
        horizon_x = []
        for width, height in ((300, 101), (560, 155)):
            settings = SoundCloudVideoSettings(
                beat_floor_far_width_percent=width, beat_floor_height=height,
                beat_floor_accent_every_four=False,
            )
            floor = Image.new("RGBA", (640, _BEAT_FLOOR_HEIGHT))
            _draw_beat_sweep(floor, (1.0,), 0.5, (220, 150, 110), settings)
            box = floor.getchannel("A").getbbox()
            self.assertEqual(box[1], 30)
            horizon_x.append(floor.getchannel("A").crop((0, 30, 640, 31)).getbbox()[0])
            near_edge.append(box[3])
            self.assertEqual(SoundCloudVideoSettings.from_json(settings.to_json()), settings)
        self.assertGreater(horizon_x[1], horizon_x[0])
        self.assertAlmostEqual(near_edge[1] - near_edge[0], 54, delta=1)

    def test_saved_depth_percentage_migrates_to_height(self):
        settings = SoundCloudVideoSettings.from_json(
            '{"beat_floor_depth_percent": 130, "beat_floor_far_width_percent": 300}'
        )
        self.assertEqual(settings.beat_floor_height, 131)
        self.assertEqual(settings.beat_floor_far_width_percent, 300)

    def test_every_fourth_beat_is_thicker_even_after_seeking(self):
        beats = tuple(0.5 * index for index in range(12))
        for index in (0, 1, 4, 8, 9):
            widths = []
            for accent in (False, True):
                floor = Image.new("RGBA", (640, _BEAT_FLOOR_HEIGHT))
                settings = SoundCloudVideoSettings(beat_floor_accent_every_four=accent)
                _draw_beat_sweep(floor, beats, beats[index], (220, 150, 110), settings)
                widths.append(sum(floor.getpixel((x, 85))[3] > 0 for x in range(308, 332)))
            self.assertEqual(widths[1] - widths[0], 3 if index % 4 == 0 else 0)
