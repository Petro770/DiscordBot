import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QProcess
from gui_launcher import BotManagerApp
from tools.notification_sounds import NotificationSounds
from tools.download_progress import ProgressReader


class ClipboardNotificationTests(unittest.TestCase):
    def manager(self, directory, enabled=True, stderr=b""):
        manager = SimpleNamespace(
            _rendered_video=None, _progress_reader=ProgressReader(), settings=Mock(),
            _download_dir=directory, _last_url="https://soundcloud.com/test/track",
            download_process=Mock(), download_status=Mock(), _append_log=Mock(),
            notification_sounds=Mock(), tray_icon=Mock(), clipboard=Mock(),
            clipboard_checkbox=Mock(), download_progress=Mock(), _read_download_progress=Mock(),
        )
        manager.clipboard_checkbox.isChecked.return_value = enabled
        manager.download_process.readAllStandardError.return_value = stderr
        manager._report_download_failure = lambda message: BotManagerApp._report_download_failure(manager, message)
        return manager

    def test_success_after_clipboard_is_updated(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "media.mp4").write_bytes(b"video")
            manager = self.manager(directory)
            BotManagerApp._download_finished(manager, 0, QProcess.ExitStatus.NormalExit)
            manager.clipboard.setMimeData.assert_called_once()
            manager.notification_sounds.play.assert_called_once_with("finished")

    def test_success_when_monitoring_was_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "media.mp4").write_bytes(b"video")
            manager = self.manager(directory, enabled=False)
            BotManagerApp._download_finished(manager, 0, QProcess.ExitStatus.NormalExit)
            manager.clipboard.setMimeData.assert_not_called()
            manager.notification_sounds.play.assert_called_once_with("finished")

    def test_video_metadata_is_optional_for_success(self):
        for metadata in (
            b'{"stage":"soundcloud_video","ffmpeg":"ffmpeg"}',
            b'{"stage":"soundcloud_video","ffmpeg":"ffmpeg","duration":10,"fps":30}',
        ):
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                video = directory / "media.mp4"
                video.write_bytes(b"video")
                manager = self.manager(directory)
                manager.download_process.readAllStandardOutput.return_value = (
                    b"CLIPBOARD_PROGRESS=" + metadata + b"\n"
                )
                manager._read_download_progress = lambda: BotManagerApp._read_download_progress(manager)

                BotManagerApp._download_finished(manager, 0, QProcess.ExitStatus.NormalExit)

                manager.clipboard.setMimeData.assert_called_once()
                manager.notification_sounds.play.assert_called_once_with("finished")
                if b'"fps"' in metadata:
                    manager.settings.setValue.assert_called_once_with(
                        "clipboard/lastSoundCloudVideo", [str(video), "ffmpeg", "10", "30"],
                    )
                else:
                    manager.settings.setValue.assert_not_called()

    def test_failure_and_invalid_output(self):
        for exit_code, status in ((1, QProcess.ExitStatus.NormalExit), (0, QProcess.ExitStatus.NormalExit), (-1, QProcess.ExitStatus.CrashExit)):
            with self.subTest(exit_code=exit_code, status=status), tempfile.TemporaryDirectory() as folder:
                manager = self.manager(Path(folder), stderr=b"LATAUSVIRHE=Test error")
                BotManagerApp._download_finished(manager, exit_code, status)
                manager.notification_sounds.play.assert_called_once_with("error")
                self.assertIsNone(manager._last_url)

    def test_failed_start_reports_error(self):
        manager = self.manager(Path("unused"))
        BotManagerApp._download_error(manager, QProcess.ProcessError.FailedToStart)
        manager.notification_sounds.play.assert_called_once_with("error")
        manager._append_log.assert_called_once()

    def test_crash_signal_waits_for_finished_to_avoid_duplicate_sound(self):
        manager = self.manager(Path("unused"))
        BotManagerApp._download_error(manager, QProcess.ProcessError.Crashed)
        manager.notification_sounds.play.assert_not_called()

    def test_bundled_files_are_short_distinct_pcm_wav(self):
        contents = set()
        directory = Path(__file__).resolve().parents[1] / "static" / "sounds"
        for name in ("started", "finished", "error"):
            with wave.open(str(directory / f"{name}.wav")) as sound:
                self.assertEqual(sound.getsampwidth(), 2)
                self.assertEqual(sound.getnchannels(), 1)
                self.assertEqual(sound.getframerate(), 44100)
                self.assertLess(sound.getnframes() / sound.getframerate(), 1)
                contents.add(sound.readframes(sound.getnframes()))
        self.assertEqual(len(contents), 3)

    def test_mute_and_replacing_previous_sound(self):
        settings = Mock()
        settings.value.return_value = True
        with patch("tools.notification_sounds.QSoundEffect", side_effect=lambda parent: Mock()):
            sounds = NotificationSounds(settings)
        sounds.play("error")
        sounds.effects["error"].play.assert_called_once()
        for effect in sounds.effects.values():
            effect.stop.assert_called_once()
        settings.value.return_value = False
        sounds.play("error")
        sounds.effects["error"].play.assert_called_once()


if __name__ == "__main__":
    unittest.main()
