"""Check the updater handoff with Qt's real detached-process return value."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


class GuiUpdateRestartTests(unittest.TestCase):
    def test_old_gui_exits_after_starting_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            # The replacement has no Discord credentials or network dependency.
            (directory / "gui_launcher.py").write_text(textwrap.dedent("""
                from pathlib import Path
                import os
                import sys
                Path("started").write_text(str(os.getpid()) + " " + " ".join(sys.argv[1:]))
            """), encoding="utf-8")
            parent_code = textwrap.dedent("""
                from pathlib import Path
                import sys
                from unittest.mock import Mock
                import gui_launcher as gui
                app = gui.QApplication([])
                app.setQuitOnLastWindowClosed(False)
                manager = gui.BotManagerApp()
                manager.show()
                gui.PROJECT_DIR = Path(sys.argv[1])
                manager._git_update = Mock()
                gui.QTimer.singleShot(0, lambda: manager._apply_update("main", "test"))
                gui.QTimer.singleShot(5000, lambda: app.exit(91))
                sys.exit(app.exec())
            """)
            parent = subprocess.Popen(
                [sys.executable, "-c", parent_code, tmp],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            )
            try:
                self.assertEqual(parent.wait(timeout=20), 0)
                marker = directory / "started"
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                pid, *args = marker.read_text().split()
                self.assertNotEqual(int(pid), parent.pid)
                self.assertEqual(args, ["--show-after-update", "--fresh-restart-environment", "--bot-stopped"])
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait()
