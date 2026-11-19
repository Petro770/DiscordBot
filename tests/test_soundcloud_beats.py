import tempfile
import unittest
import wave
from array import array
from math import exp, pi, sin
from pathlib import Path
from shutil import which

from PIL import Image

from tools.soundcloud_beats import estimate_beat_grid, read_beat_grid
from tools.soundcloud_video import _draw_beat_line


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

    def test_marker_moves_left_and_highlights_at_playhead(self):
        before = Image.new("RGBA", (640, 112))
        at_beat = before.copy()
        _draw_beat_line(before, (1.0,), 0.5, 3.4)
        _draw_beat_line(at_beat, (1.0,), 1.0, 3.4)
        self.assertEqual(before.getpixel((414, 102))[3], 200)
        self.assertEqual(before.getpixel((320, 102))[3], 0)
        self.assertEqual(at_beat.getpixel((320, 102))[3], 255)
