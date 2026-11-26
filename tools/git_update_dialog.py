"""Branch picker for the desktop updater."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFrame, QLabel, QRadioButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from tools.git_update import RemoteBranch


class GitUpdateDialog(QDialog):
    def __init__(self, current: str, commit: str, branches: list[RemoteBranch], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Git-päivitys")
        self.resize(640, 510)
        self._branches = branches
        self._choices = QButtonGroup(self)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label(f"Nykyinen versio: {current or 'irrotettu HEAD'} · {commit}"))
        layout.addWidget(self._label("Valitse päivitettävä haara. Päivitys käynnistää hallintapaneelin uudelleen."))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        cards = QWidget(scroll)
        card_layout = QVBoxLayout(cards)
        scroll.setWidget(cards)
        layout.addWidget(scroll, 1)

        for index, branch in enumerate(branches):
            card = QFrame(cards)
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setAutoFillBackground(True)
            content = QVBoxLayout(card)
            same_branch = branch.name == current
            same_commit = branch.commit.startswith(commit)
            status = "Ajan tasalla" if same_commit else "Etäversio eroaa"
            title = branch.name
            if same_branch:
                title += f"  ·  Nykyinen haara  ·  {status}"

            choice = QRadioButton(title.replace("&", "&&"), card)
            self._choices.addButton(choice, index)
            content.addWidget(choice)
            content.addWidget(self._label(branch.subject or "Commitilla ei ole otsikkoa."))
            content.addWidget(self._label(f"{branch.date}  ·  {branch.author}  ·  {branch.commit[:8]}"))
            card_layout.addWidget(card)

        card_layout.addStretch()
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        default = next((i for i, b in enumerate(branches) if b.name == current), None)
        if default is None:
            default = next((i for i, b in enumerate(branches) if b.name == "main"), 0)
        self._choices.button(default).setChecked(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        update = buttons.button(QDialogButtonBox.StandardButton.Ok)
        update.setText("Päivitä ja käynnistä uudelleen")
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Peruuta")
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_branch(self) -> RemoteBranch:
        return self._branches[self._choices.checkedId()]

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(text)
        label.setWordWrap(True)
        return label
