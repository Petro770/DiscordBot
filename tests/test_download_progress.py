import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from tools.download_progress import ProgressReader, report, download_hook


class DownloadProgressTests(unittest.TestCase):
    def test_split_utf8_and_unrelated_output(self):
        reader = ProgressReader()
        event = dict(stage="analysis", detail="Äänen analyysi", percent=None)
        raw = ("yt-dlp output\nCLIPBOARD_PROGRESS=" + json.dumps(event, ensure_ascii=False) + "\n").encode()
        output = []
        for byte in raw:
            output.extend(reader.feed(bytes([byte])))
        self.assertEqual(output, [event])

    def test_bad_messages_are_ignored_and_buffer_is_bounded(self):
        reader = ProgressReader()
        self.assertEqual(reader.feed(b'CLIPBOARD_PROGRESS=broken\nCLIPBOARD_PROGRESS=[]\n'), [])
        reader.feed(b"x" * 100000)
        self.assertLessEqual(len(reader.buffer), 65536)

    def test_reports_are_opt_in_and_download_hook_reports_conversion(self):
        stream = io.StringIO()
        with patch("tools.download_progress._enabled", False), redirect_stdout(stream):
            report("analysis", "test")
        self.assertEqual(stream.getvalue(), "")
        with patch("tools.download_progress._enabled", True), redirect_stdout(stream):
            hook = download_hook()
            hook(dict(status="downloading", total_bytes=100, downloaded_bytes=25, speed=10, eta=7))
            hook(dict(status="finished"))
        events = ProgressReader().feed(stream.getvalue().encode())
        self.assertEqual(events[0]["percent"], 25)
        self.assertEqual(events[0]["speed"], 10)
        self.assertEqual(events[1]["stage"], "audio")
