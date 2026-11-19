import tempfile
import unittest
import wave
from array import array
from math import exp, pi, sin
from pathlib import Path
from shutil import which

from PIL import Image

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
            _draw_beat_sweep(floor, (1.0,), now, (220, 150, 110))
            alpha = floor.getchannel("A")
            positions.append([alpha.crop((0, y, 640, y + 1)).getbbox()[0] for y in (112, 200)])
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
