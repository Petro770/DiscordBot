"""Edit the local dotenv file without changing the running process."""
import io
import os
import stat
import tempfile
from pathlib import Path

from dotenv.parser import parse_stream
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout


def _read_local(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def save_env(path: Path, original: bytes | None, text: str):
    for binding in parse_stream(io.StringIO(text)):
        if binding.error:
            raise ValueError(f".env-syntaksivirhe rivillä {binding.original.line}.")
    if _read_local(path) != original:
        raise ValueError(".env muuttui levyllä. Sulje muokkain ja avaa se uudelleen.")

    mode = stat.S_IMODE(path.stat().st_mode) if original is not None else None
    encoding = "utf-8-sig" if original and original.startswith(b"\xef\xbb\xbf") else "utf-8"
    if original and b"\r\n" in original:
        text = text.replace("\n", "\r\n")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text.encode(encoding))
        if mode is not None:
            temporary.chmod(mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class EnvEditor(QDialog):
    def __init__(self, path, template, parent=None):
        super().__init__(parent)
        self.path = path
        self.original = _read_local(path)
        self.setWindowTitle("Muokkaa .env-tiedostoa")
        self.resize(760, 530)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Muutokset tulevat käyttöön seuraavalla käynnistyksellä. Tiedosto voi sisältää salaisuuksia."))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(self.original.decode("utf-8-sig") if self.original is not None
                               else template.read_text(encoding="utf-8-sig"))
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Tallenna")
        buttons.button(QDialogButtonBox.Cancel).setText("Peruuta")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            save_env(self.path, self.original, self.edit.toPlainText())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, ".env-tallennus", str(exc))
            return
        self.accept()
