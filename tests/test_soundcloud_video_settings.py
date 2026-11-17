import unittest
from unittest.mock import Mock, patch
from array import array

from tools.soundcloud_video_settings import MAX_VIDEO_BANDS, SoundCloudVideoSettings
from tools.soundcloud_video import _WaveStrip, _encode_video, _band_styles, _wave_centers, _envelope_at, _wave_frames, _wave_alpha, _wave_palette


class SoundCloudVideoSettingsTests(unittest.TestCase):
    def test_json_round_trip(self):
        settings = SoundCloudVideoSettings(fps=29, bands=30, audio_kbps=256, wave_line_width=5)
        self.assertEqual(settings, SoundCloudVideoSettings.from_json(settings.to_json()))

    def test_invalid_values(self):
        for values in ({"fps": 0}, {"fps": True}, {"resolution": 641},
                       {"bands": MAX_VIDEO_BANDS + 1}, {"wave_line_width": 0}, {"wave_line_width": 13}, {"preset": "unknown"}, {"audio_kbps": 321},
                       {"auto_compress": "false"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                SoundCloudVideoSettings(**values)

    def test_interpolation_and_edges(self):
        band = array("f", [0, 1, 0])
        self.assertEqual(_envelope_at(band, 0.25), 0.25)
        self.assertEqual(_envelope_at(band, 0.75), 0.75)
        self.assertEqual(_envelope_at(band, 1.5), 0.5)
        self.assertEqual(_envelope_at(array("f", [1, 1]), -20), 1)
        self.assertEqual(_envelope_at(array("f", [1, 1]), 20), 1)

    def test_subpixel_motion_changes_frames_smoothly(self):
        # Small amplitude changes used to round to exactly the same pixel row.
        from PIL import Image, ImageChops
        settings = SoundCloudVideoSettings(fps=60, bands=1, wave_amplitude=1)
        frames = iter(_wave_frames((array("f", [i / 120 for i in range(120)]),), settings))
        images = [Image.frombytes("RGBA", (640, 112), next(frames)) for _ in range(3)]
        for first, second in zip(images, images[1:]):
            self.assertIsNotNone(ImageChops.difference(first, second).convert("RGB").getbbox())

    def test_opacity_tracks_strength_without_amplifying_quiet_bands(self):
        self.assertLess(_wave_alpha(0, 1), _wave_alpha(0.1, 1))
        self.assertLess(_wave_alpha(0.1, 1), _wave_alpha(1, 1))
        self.assertEqual(_wave_alpha(2, 1), _wave_alpha(1, 1))

    def test_opacity_boost_and_more_aggressive_response(self):
        for strength in (0, 0.01, 0.1, 0.3, 0.5, 1):
            old = round(28 + 207 * strength ** 0.65)
            self.assertGreaterEqual(_wave_alpha(strength, 1), min(255, round(old * 1.3)) - 1)
        self.assertEqual(_wave_alpha(1, 1), 255)

    def test_all_bands_fit_at_max_amplitude_and_line_width(self):
        from PIL import Image
        for count in range(1, MAX_VIDEO_BANDS + 1):
            with self.subTest(count=count):
                settings = SoundCloudVideoSettings(bands=count, fps=1, wave_amplitude=48, wave_line_width=12)
                centers = _wave_centers(_band_styles(settings), settings)
                self.assertGreaterEqual(min(centers) - 48 - 6, 3)
                self.assertLessEqual(max(centers) + 6, 108)
                for level in (0, 1):
                    envelopes = tuple(array("f", [level]) for _ in range(count))
                    image = Image.frombytes("RGBA", (640, 112), next(_wave_frames(envelopes, settings)))
                    alpha = image.getchannel("A")
                    self.assertIsNotNone(alpha.getbbox())
                    self.assertIsNone(alpha.crop((0, 0, 640, 1)).getbbox())
                    self.assertIsNone(alpha.crop((0, 111, 640, 112)).getbbox())

    def test_palette_uses_cover_and_warms_bass(self):
        from PIL import Image
        blue = _wave_palette(Image.new("RGB", (32, 32), "navy"), 3)
        green = _wave_palette(Image.new("RGB", (32, 32), "green"), 3)
        self.assertNotEqual(blue, green)
        self.assertGreater(blue[0][0] - blue[0][2], blue[-1][0] - blue[-1][2])
        for count in range(1, MAX_VIDEO_BANDS + 1):
            self.assertEqual(len(_wave_palette(None, count)), count)

    def test_only_upper_outline_is_drawn(self):
        from PIL import Image
        settings = SoundCloudVideoSettings(bands=1, wave_opacity=0)
        raw = next(_wave_frames((array("f", [1] * 120),), settings))
        image = Image.frombytes("RGBA", (640, 112), raw)
        # Single band baseline is at 56; no mirror and no filled interior below the line.
        self.assertIsNone(image.getchannel("A").crop((0, 35, 640, 112)).getbbox())
        self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_full_width_edges_fade_and_background_is_optional(self):
        from PIL import Image
        envelope = (array("f", [1] * 120),)
        for background in (False, True):
            settings = SoundCloudVideoSettings(bands=1, wave_background=background)
            image = Image.frombytes("RGBA", (640, 112), next(_wave_frames(envelope, settings)))
            alpha = image.getchannel("A")
            self.assertEqual(alpha.getpixel((0, 24)), 0)
            self.assertEqual(alpha.getpixel((639, 24)), 0)
            self.assertGreater(alpha.getpixel((64, 24)), alpha.getpixel((12, 24)))
            self.assertEqual(alpha.getpixel((320, 100)) > 0, background)

    def test_line_width_changes_rendered_coverage(self):
        from PIL import Image
        envelope = (array("f", [1] * 120),)
        coverage = []
        for width in (1, 4, 12):
            settings = SoundCloudVideoSettings(bands=1, wave_line_width=width)
            image = Image.frombytes("RGBA", (640, 112), next(_wave_frames(envelope, settings)))
            coverage.append(sum(value * count for value, count in enumerate(image.getchannel("A").histogram())))
        self.assertLess(coverage[0], coverage[1])
        self.assertLess(coverage[1], coverage[2])

    def test_strip_tiles_are_reused_bounded_and_seamless(self):
        settings = SoundCloudVideoSettings(bands=1)
        strip = _WaveStrip(array("f", [1] * 1200), 32, 1.5, (200, 150, 150), 1, settings)
        tile = strip._tile(0)
        self.assertIs(tile, strip._tile(0))
        following = strip._tile(1)
        self.assertEqual(tile.crop((1023, 0, 1024, strip.height)).tobytes(),
                         following.crop((0, 0, 1, strip.height)).tobytes())
        for index in range(10):
            strip._tile(index)
        self.assertLessEqual(len(strip.tiles), strip.CACHE_TILES)
        strip.frame(100)
        source = strip.source
        strip.frame(100.1)
        self.assertIs(source, strip.source)

    def _run_watchdog(self, ticks):
        clock = [0]
        timers = []
        process = Mock()
        process.pid = 123
        process.poll.return_value = None
        process.wait.return_value = 0
        process.stdin = Mock()
        process.stdin.__enter__ = Mock(return_value=Mock())
        process.stdin.__exit__ = Mock(return_value=False)
        def timer(interval, callback):
            timers.append((interval, callback, Mock()))
            return timers[-1][2]
        def frames(*args):
            yield b"frame"
            for now in ticks:
                clock[0] = now
                timers[-1][1]()
                yield b"frame"
        context = Mock()
        context.__enter__ = Mock(return_value=process)
        context.__exit__ = Mock(return_value=False)
        with patch("tools.soundcloud_video.monotonic", side_effect=lambda: clock[0]), \
             patch("tools.soundcloud_video.Timer", side_effect=timer), \
             patch("tools.soundcloud_video.subprocess.Popen", return_value=context), \
             patch("tools.soundcloud_video._wave_frames", side_effect=frames):
            _encode_video(["ffmpeg"], (array("f", [1] * 120),), None,
                          SoundCloudVideoSettings(encode_timeout=30))
        return process, timers

    def test_watchdog_allows_long_render_with_progress(self):
        process, timers = self._run_watchdog((20, 40, 60))
        process.kill.assert_not_called()
        self.assertEqual(len(timers), 4)
        timers[-1][2].cancel.assert_called_once()
        timers[-1][1]()
        process.kill.assert_not_called()

    def test_watchdog_still_kills_a_stalled_encoder(self):
        process, timers = self._run_watchdog((31,))
        process.kill.assert_called_once()
        timers[-1][2].cancel.assert_called_once()

    def test_non_divisor_fps_keeps_duration(self):
        # 29 FPS must produce 29 frames per second, without integer-step drift.
        envelope = (array("f", [0.1] * 120),)
        for fps in (1, 15, 29, 59, 60):
            with self.subTest(fps=fps):
                frames = _wave_frames(envelope, SoundCloudVideoSettings(fps=fps, bands=1))
                self.assertEqual(sum(1 for _ in frames), fps)


if __name__ == "__main__":
    unittest.main()
