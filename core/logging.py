"""Loggaus ja apufunktiot."""
import logging
import os


def _create_logger() -> logging.Logger:
    """Luo 'bot'-loggerin vain tiedostokäsittelijällä.

    Konsoliloki (StreamHandler) lisätään erikseen enable_console()-kutsulla,
    jotta GUI-versio ei kirjoita stdoutiin.
    """
    logger = logging.getLogger("bot")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    log_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(log_dir, "bot_runtime.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def enable_console(level: int = logging.INFO) -> None:
    """Lisää konsolilokin (stdout). Kutsu vain CLI-muodoissa."""
    logger = logging.getLogger("bot")
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

class PyQtLogHandler(logging.Handler):
    """Bridgen logging-viestit PyQt-signaalille.

    Käyttö:
        handler = PyQtLogHandler(callback)
        log.addHandler(handler)
        # ...
        log.removeHandler(handler)
    """

    def __init__(self, callback: callable):
        super().__init__(level=logging.DEBUG)
        self._callback = callback
        self.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self._callback(msg)
        except Exception:
            self.handleError(record)


log = _create_logger()

