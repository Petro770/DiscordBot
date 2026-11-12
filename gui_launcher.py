import asyncio
import os
import sys
import threading
import time
import traceback
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget,
    QPushButton, QSystemTrayIcon, QTextEdit, QMenu
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QThread

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
        self.setup_ui()

        self.discord_client = create_bot()
        self.print_queue = PrintQueue()
        register_events(self.discord_client, self.print_queue)
        self._is_running = False
        self.worker = None
        self.worker_thread = None

        self.tray_icon = self._init_tray_icon()
        self.tray_icon.activated.connect(self._on_tray_icon_activated)

    def _init_tray_icon(self) -> QSystemTrayIcon:
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "static", "glorp.ico"
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

        self.worker = BotWorker(self.discord_client, self.print_queue)
        self.worker_thread = QThread(self)
        self.worker.moveToThread(self.worker_thread)

        self.worker.log_signal.connect(self.log_update)
        self.worker.status_signal.connect(self.status_update)
        self.worker.error_signal.connect(self.handle_error)
        self.worker_thread.started.connect(self.worker.run_bot)
        self.worker_thread.finished.connect(self._on_thread_finished)

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
        self._append_log("Taustasäie on päättynyt.")
        if self.worker:
            self.worker.deleteLater()
        if self.worker_thread:
            self.worker_thread.deleteLater()
        self._is_running = False

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

    manager.start_bot_service()
    manager.hide()
    manager.tray_icon.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

