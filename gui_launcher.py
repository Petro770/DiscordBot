import asyncio
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from uuid import uuid4
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget,
    QCheckBox, QPushButton, QSystemTrayIcon, QTextEdit, QMenu, QMessageBox
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QMimeData, QObject, QProcess, QProcessEnvironment, QSettings, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot

from tools.clipboard_download import MAX_FILE_BYTES, clipboard_url
from tools.notification_sounds import NotificationSounds
from tools.download_progress import ProgressReader
from tools.download_progress_widget import DownloadProgressWidget
from tools.git_update import GitUpdate, UpdateError
from tools.git_update_dialog import GitUpdateDialog
from tools.ai_monitor import AiMonitor

PROJECT_DIR = Path(__file__).resolve().parent

import discord
import config
from printer.queue import PrintQueue
from bot.client import create_bot, register_events
from core.logging import log, PyQtLogHandler


class BotWorker(QObject):
    """Botin päälogiikka erillisessä säikeessä.

    Signaalit:
        log_signal  -> GUI:n QTextEdit (yhdistetty _append_logiin)
        status_signal -> GUI:n status_label (yhdistetty status_updateen)
        error_signal  -> GUI:n status_label + QTextEdit (yhdistetty handle_erroriin)
    """

    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, client, print_queue):
        super().__init__()
        self.client = client
        self.print_queue = print_queue
        self._is_running = False
        self._loop = None

    def _emit(self, msg: str):
        """Yhteinen emit. Kirjoittaa tiedostolokiin ja lähettää GUI:lle."""
        log.info(msg)
        try:
            self.log_signal.emit(msg)
        except RuntimeError:
            pass

    def _emit_signal_only(self, msg: str):
        """Lähettää vain PyQt-signaalin. EI kutsu log.info()a.

        Käytetään PyQtLogHandlerin callbackina rekursion välttämiseksi.
        """
        try:
            self.log_signal.emit(msg)
        except RuntimeError:
            pass

    def _emit_error(self, msg: str):
        """Viriheviestin lähetys."""
        log.error(msg)
        try:
            self.log_signal.emit(f"VIRHE: {msg}")
            self.error_signal.emit(msg)
        except RuntimeError:
            pass

    def _set_status(self, msg: str):
        """Päivitä vain status_label (ei lisää logiin uudestaan)."""
        try:
            self.status_signal.emit(msg)
        except RuntimeError:
            pass

    @pyqtSlot()
    def run_bot(self):
        handler = PyQtLogHandler(self._emit_signal_only)
        log.addHandler(handler)

        try:
            thread_name = threading.current_thread().name
            self._emit(f"run_bot käynnistyi säikeessä '{thread_name}'")
            self._set_status("Alustetaan...")

            has_token = "oikea" if config.TOKEN else "PUUTUU"
            self._emit(f"TOKEN: {has_token}")
            self._emit(f"client-tyyppi: {type(self.client).__name__}")

            if not config.TOKEN:
                raise RuntimeError("DISCORD_TOKEN puuttuu config.py-tiedostosta.")

            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            self._emit("Discord-yhteyttä muodostetaan...")
            self._set_status("Yhteys muodostetaan...")

            self._loop.run_until_complete(self.client.start(config.TOKEN))

        except discord.LoginFailure as e:
            self._emit_error(f"Discord-tunnukset virheelliset: {e}")
            self._set_status("VIRHE: tunnusvirhe")
        except discord.PrivilegedIntentsRequired as e:
            self._emit_error(
                "Privileged intent puuttuu. Ota Message Content Intent käyttöön "
                "Discord Developer Portalista."
            )
            self._set_status("VIRHE: intent puuttuu")
        except Exception as e:
            tb = traceback.format_exc()
            self._emit_error(f"{type(e).__name__}: {e}")
            log.debug(tb)
            self._set_status("VIRHE: odottamaton virhe")
        finally:
            log.removeHandler(handler)
            if self._loop and not self._loop.is_closed():
                try:
                    self._loop.run_until_complete(self.client.close())
                except Exception:
                    pass
                self._loop.close()
            self._is_running = False
            self._emit("Event loop suljettu.")
            self._set_status("Pysäytetty")

    def stop_bot(self):
        self._is_running = False
        if self._loop and self._loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self.client.close(), self._loop)
                fut.result(timeout=5)
            except Exception as e:
                self._emit_error(f"Sulkeminen epäonnistui: {e}")

class BotManagerApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bot-Hallintapaneeli")
        self.setGeometry(100, 100, 500, 350)
        self._git_update = GitUpdate(PROJECT_DIR)
        self._version_check = QProcess(self)
        self._version_check.setWorkingDirectory(str(PROJECT_DIR))
        git_environment = QProcessEnvironment.systemEnvironment()
        git_environment.insert("GIT_TERMINAL_PROMPT", "0")
        self._version_check.setProcessEnvironment(git_environment)
        self._version_check.finished.connect(self._version_check_finished)
        self._version_check.errorOccurred.connect(self._version_check_error)
        self._version_timer = QTimer(self)
        self._version_timer.setSingleShot(True)
        self._version_timer.timeout.connect(self._version_check.kill)
        self._ai_monitor = AiMonitor(self)
        self.setup_ui()
        self.notification_sounds = NotificationSounds(self.settings, self)

        self._is_running = False
        self.worker = None
        self.worker_thread = None

        self.tray_icon = self._init_tray_icon()
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self._clipboard_changed)
        self.download_process = QProcess(self)
        self.download_process.setWorkingDirectory(str(PROJECT_DIR))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        self.download_process.setProcessEnvironment(environment)
        self._progress_reader = ProgressReader()
        self._rendered_video = None
        self.download_process.readyReadStandardOutput.connect(self._read_download_progress)
        self.download_process.started.connect(lambda: self.notification_sounds.play("started"))
        self.download_process.finished.connect(self._download_finished)
        self.download_process.errorOccurred.connect(self._download_error)
        self._download_dir = None
        self._last_url = None

    def _init_tray_icon(self) -> QSystemTrayIcon:
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "static", "bot.ico"
        )
        if os.path.exists(icon_path):
            return QSystemTrayIcon(QIcon(icon_path), self)
        return QSystemTrayIcon(QIcon(), self)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.status_label = QLabel("Tila: ei käynnissä")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_view.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 11px;"
        )
        layout.addWidget(self.log_view)

        self.start_button = QPushButton("Käynnistä")
        self.start_button.clicked.connect(self.start_bot_service)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Pysäytä")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_bot_service)
        layout.addWidget(self.stop_button)

        self.update_button = QPushButton("Tarkista versio…")
        self.update_button.clicked.connect(self._check_version)
        layout.addWidget(self.update_button)

        ai_button = QPushButton("AI-keskustelut…")
        ai_button.clicked.connect(self._show_ai_monitor)
        layout.addWidget(ai_button)

        self.clipboard_checkbox = QCheckBox("Seuraa leikepöydän medialinkkejä (150 MB)")
        self.clipboard_checkbox.toggled.connect(self._clipboard_toggled)
        layout.addWidget(self.clipboard_checkbox)
        self.soundcloud_video_checkbox = QCheckBox("SoundCloud leikepöydälle MP4-videona")
        self.settings = QSettings("DiscordBot", "Launcher")
        self.soundcloud_video_checkbox.setChecked(
            self.settings.value("clipboard/soundcloudVideo", True, type=bool)
        )
        self.soundcloud_video_checkbox.toggled.connect(
            lambda enabled: self.settings.setValue("clipboard/soundcloudVideo", enabled)
        )
        layout.addWidget(self.soundcloud_video_checkbox)
        self.soundcloud_settings_button = QPushButton("SoundCloud-videon asetukset…")
        self.soundcloud_settings_button.clicked.connect(self._open_soundcloud_settings)
        layout.addWidget(self.soundcloud_settings_button)
        self.notification_sounds_checkbox = QCheckBox("Leikepöytälatausten äänimerkit")
        self.notification_sounds_checkbox.setChecked(
            self.settings.value("clipboard/notificationSounds", True, type=bool)
        )
        self.notification_sounds_checkbox.toggled.connect(
            lambda enabled: self.settings.setValue("clipboard/notificationSounds", enabled)
        )
        layout.addWidget(self.notification_sounds_checkbox)
        self.download_progress = DownloadProgressWidget(self)
        layout.addWidget(self.download_progress)
        self.download_status = QLabel()
        self.download_status.setWordWrap(True)
        layout.addWidget(self.download_status)

    def _show_ai_monitor(self):
        self._ai_monitor.show()
        self._ai_monitor.raise_()
        self._ai_monitor.activateWindow()

    def _check_version(self):
        try:
            self._git_update.current()
        except UpdateError as exc:
            QMessageBox.warning(self, "Git-päivitys", str(exc))
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("Tarkistetaan versiota…")
        self._version_timer.start(60000)
        self._version_check.start(
            "git", ["fetch", "--prune", "--no-tags", "origin", "+refs/heads/*:refs/remotes/origin/*"]
        )

    def _restore_update_button(self):
        self._version_timer.stop()
        self.update_button.setText("Tarkista versio…")
        self.update_button.setEnabled(True)

    def _version_check_error(self, error):
        if error == QProcess.FailedToStart:
            self._restore_update_button()
            QMessageBox.warning(self, "Git-päivitys", "Git-komentoa ei saatu käynnistettyä.")

    def _version_check_finished(self, exit_code, exit_status):
        self._restore_update_button()
        if exit_code != 0 or exit_status != QProcess.NormalExit:
            details = bytes(self._version_check.readAllStandardError()).decode("utf-8", errors="replace").strip()
            QMessageBox.warning(self, "Git-päivitys", details or "Versiotarkistus keskeytyi tai aikakatkaistiin.")
            return

        try:
            current, short_commit = self._git_update.current()
            branches = self._git_update.branches()
            if not branches:
                raise UpdateError("Origin-etävarastosta ei löytynyt haaroja.")
            dialog = GitUpdateDialog(current, short_commit, branches, self)
            if not dialog.exec_():
                return
            selected = dialog.selected_branch()
            branch, commit = selected.name, selected.commit
            if not self._git_update.check(branch, commit):
                QMessageBox.information(self, "Git-päivitys", "Valittu haara on ajan tasalla.")
                return
            if self.download_process.state() != QProcess.NotRunning:
                raise UpdateError("Medialataus on kesken. Odota sen valmistumista ennen päivitystä.")
            self._apply_update(branch, commit)
        except UpdateError as exc:
            QMessageBox.warning(self, "Git-päivitys", str(exc))

    def _apply_update(self, branch, commit):
        self._git_update.check(branch, commit)
        was_running = self._is_running
        self.stop_bot_service()
        if self.worker_thread and self.worker_thread.isRunning():
            raise UpdateError("Botin taustasäie ei pysähtynyt. Päivitys keskeytettiin.")
        try:
            self._git_update.apply(branch, commit)
        except UpdateError:
            if was_running:
                self.start_bot_service()
            raise
        arguments = [str(PROJECT_DIR / "gui_launcher.py"), "--show-after-update"]
        if not was_running:
            arguments.append("--bot-stopped")
        python = Path(sys.executable)
        if python.name.lower() == "python.exe" and python.with_name("pythonw.exe").is_file():
            python = python.with_name("pythonw.exe")
        started, _ = QProcess.startDetached(str(python), arguments, str(PROJECT_DIR))
        if not started:
            raise UpdateError("Päivitys tehtiin, mutta hallintapaneelin uudelleenkäynnistys epäonnistui. Avaa se uudelleen.")
        self.quit_application()

    def _open_soundcloud_settings(self):
        from tools.soundcloud_settings_dialog import SoundCloudSettingsDialog
        SoundCloudSettingsDialog(self.settings, self).exec_()

    def _clipboard_toggled(self, enabled):
        self._last_url = None
        if enabled:
            self._clipboard_changed()

    def _clipboard_changed(self):
        if not self.clipboard_checkbox.isChecked():
            return
        url = clipboard_url(self.clipboard.text())
        if url == self._last_url:
            return
        if url is None:
            self._last_url = None
            return
        if self.download_process.state() != QProcess.NotRunning:
            self.download_status.setText("Lataus on käynnissä. Kopioi uusi linkki sen jälkeen.")
            return
        self._last_url = url
        self._download_dir = PROJECT_DIR / "clipboard_downloads" / uuid4().hex
        self.download_status.setText("Ladataan mediaa…")
        self._progress_reader = ProgressReader()
        self._rendered_video = None
        self.download_progress.begin()
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe" and python.with_name("python.exe").is_file():
            python = python.with_name("python.exe")
        arguments = ["-m", "tools.clipboard_download", url, str(self._download_dir), "--progress"]
        if not self.soundcloud_video_checkbox.isChecked():
            arguments.append("--soundcloud-mp3")
        arguments.extend([
            "--soundcloud-video-settings",
            self.settings.value("clipboard/soundcloudVideoSettings", "{}"),
        ])
        self.download_process.start(str(python), arguments)

    def _read_download_progress(self):
        chunk = bytes(self.download_process.readAllStandardOutput())
        for event in self._progress_reader.feed(chunk):
            if event["stage"] == "preview":
                self.download_progress.update_preview(event.get("image"))
            elif event["stage"] == "soundcloud_video":
                if all(event.get(key) is not None for key in ("ffmpeg", "duration", "fps")):
                    self._rendered_video = event
            else:
                self.download_progress.update_progress(event)

    def _download_finished(self, exit_code, exit_status):
        self._read_download_progress()
        errors = bytes(self.download_process.readAllStandardError()).decode("utf-8", errors="replace")
        if exit_code == 0 and exit_status == QProcess.NormalExit:
            files = list(self._download_dir.glob("media.*"))
            if len(files) == 1 and files[0].is_file() and 0 < files[0].stat().st_size <= MAX_FILE_BYTES:
                self.download_progress.finish(True)
                if self._rendered_video and files[0].suffix.lower() == ".mp4":
                    video = self._rendered_video
                    self.settings.setValue("clipboard/lastSoundCloudVideo", [
                        str(files[0]), video["ffmpeg"], str(video["duration"]), str(video["fps"]),
                    ])
                if not self.clipboard_checkbox.isChecked():
                    self.download_status.setText(f"Lataus tallennettu kansioon {self._download_dir.name}.")
                    self.notification_sounds.play("finished")
                    return
                data = QMimeData()
                data.setUrls([QUrl.fromLocalFile(str(files[0]))])
                self.clipboard.setMimeData(data)
                message = "Tiedosto on leikepöydällä. Liitä Discordiin painamalla Ctrl+V."
                self.download_status.setText(message)
                self.notification_sounds.play("finished")
                self.tray_icon.showMessage("Lataus valmis", message)
                return
        self._last_url = None
        message = next(
            (line.removeprefix("LATAUSVIRHE=") for line in reversed(errors.splitlines())
             if line.startswith("LATAUSVIRHE=")),
            "Medialataus epäonnistui.",
        )
        self._report_download_failure(message)

    def _report_download_failure(self, message):
        self.download_progress.finish(False)
        self.download_status.setText(message)
        self._append_log(message)
        self.notification_sounds.play("error")
        self.tray_icon.showMessage("Lataus epäonnistui", message)

    def _download_error(self, error):
        if error == QProcess.FailedToStart:
            self._last_url = None
            self._report_download_failure("Latausprosessia ei voitu käynnistää.")

    def _append_log(self, message: str):
        """Ainoa paikka, missä QTextEditiin kirjoitetaan."""
        timestamp = time.strftime("%H:%M:%S")
        self.log_view.append(f"[{timestamp}] {message}")
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    @pyqtSlot(str)
    def status_update(self, msg: str):
        """Päivitä VAIN status_label. Ei lisää logiin (se tulee log_signalista)."""
        self.status_label.setText(f"Tila: {msg}")

    @pyqtSlot(str)
    def handle_error(self, msg: str):
        """Päivitä status_label virhetilaan. Logiin kirjoittaa log_signal."""
        self.status_label.setText("Tila: VIRHE")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    @pyqtSlot(str)
    def log_update(self, msg: str):
        """Ainoa paikka, missä viesti menee QTextEditiin."""
        self._append_log(msg)

    def start_bot_service(self):
        if self._is_running:
            return
        self._append_log("Botin käynnistys aloitettu.")
        self._set_status_text("Käynnistyy...")

        self.discord_client = create_bot()
        self.print_queue = PrintQueue()
        register_events(self.discord_client, self.print_queue)
        self.worker = BotWorker(self.discord_client, self.print_queue)
        self.worker_thread = QThread(self)
        self.worker.moveToThread(self.worker_thread)

        self.worker.log_signal.connect(self.log_update)
        self.worker.status_signal.connect(self.status_update)
        self.worker.error_signal.connect(self.handle_error)
        self.worker_thread.started.connect(self.worker.run_bot)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self._on_thread_finished)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()
        self._is_running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def _set_status_text(self, text: str):
        self.status_label.setText(text)

    def stop_bot_service(self):
        if not self._is_running:
            return
        self._append_log("Botin pysäytys aloitettu...")
        self._is_running = False

        if self.worker:
            self.worker.stop_bot()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            if not self.worker_thread.wait(8000):
                self._append_log("Varoitus: säie ei päättynyt 8s kuluessa. Pakotetaan.")
                self.worker_thread.terminate()
                self.worker_thread.wait(2000)

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._set_status_text("Pysäytetty")

    def _on_thread_finished(self):
        if self.sender() is not self.worker_thread:
            return
        self._append_log("Taustasäie on päättynyt.")
        self._is_running = False
        self.worker = None
        self.worker_thread = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()
                self.raise_()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Bot-Hallintapaneeli",
            "Sovellus jatkaa system tray:ssä.",
            QSystemTrayIcon.Information,
            2000
        )

    def quit_application(self):
        if self._version_check.state() != QProcess.NotRunning:
            self._version_check.blockSignals(True)
            self._version_check.kill()
            self._version_check.waitForFinished(2000)
        if self.download_process.state() != QProcess.NotRunning:
            self.clipboard_checkbox.setChecked(False)
            self.download_process.finished.disconnect(self._download_finished)
            self.download_process.kill()
            self.download_process.waitForFinished(2000)
        self._append_log("Sovellus lopetetaan.")
        self.stop_bot_service()
        self.tray_icon.hide()
        QApplication.quit()

def main():
    # GUI-versio: EI konsolilokia. Loki kirjoitetaan vain tiedostoon ja GUI:hin.
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    manager = BotManagerApp()

    tray_menu = QMenu()
    action_show = tray_menu.addAction("Näytä ikkuna")
    action_show.triggered.connect(
        lambda: (manager.show(), manager.activateWindow(), manager.raise_())
    )
    action_quit = tray_menu.addAction("Poistu")
    action_quit.triggered.connect(manager.quit_application)
    manager.tray_icon.setContextMenu(tray_menu)

    if "--bot-stopped" not in sys.argv:
        manager.start_bot_service()
    if "--show-after-update" in sys.argv:
        manager.show()
    else:
        manager.hide()
    manager.tray_icon.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

