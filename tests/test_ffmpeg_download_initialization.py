import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from core.models import NonRetryableError
from downloaders.base import ffmpeg_executables
from downloaders.youtube import _download_sync


class FfmpegDownloadInitializationTests(unittest.TestCase):
    def setUp(self):
        ffmpeg_executables.cache_clear()
        self.addCleanup(ffmpeg_executables.cache_clear)

    def test_downloader_import_does_not_initialize_ffmpeg(self):
        subprocess.run([sys.executable, "-c", """
from unittest.mock import patch
with patch("static_ffmpeg.run.get_or_fetch_platform_executables_else_raise",
           side_effect=PermissionError("lock.file")) as initialize:
    from downloaders.youtube import is_youtube
    assert is_youtube("https://www.youtube.com/watch?v=abcdefghijk")
    initialize.assert_not_called()
"""], check=True)

    def test_permission_error_during_download_is_reportable(self):
        with patch("downloaders.base.shutil.which", return_value=None), patch(
            "static_ffmpeg.run.get_or_fetch_platform_executables_else_raise",
            side_effect=PermissionError("lock.file"),
        ):
            with self.assertRaises(NonRetryableError) as caught:
                _download_sync("https://www.youtube.com/watch?v=abcdefghijk")
        self.assertIn(".venv", caught.exception.user_facing)
        self.assertIn("lock.file", str(caught.exception))

    def test_path_installation_avoids_static_ffmpeg(self):
        with patch("downloaders.base.shutil.which", side_effect=[
            os.path.join("bin", "ffmpeg"), os.path.join("bin", "ffprobe"),
        ]), patch("static_ffmpeg.run.get_or_fetch_platform_executables_else_raise") as initialize:
            self.assertEqual(ffmpeg_executables(), (os.path.join("bin", "ffmpeg"), os.path.join("bin", "ffprobe")))
            initialize.assert_not_called()
