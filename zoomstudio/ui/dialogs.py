"""Confirmation dialog used for every destructive or pedal-writing question."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import strings as S


class ConfirmDialog(QDialog):
    """Title, message and two buttons; Cancel is the default and Escape. ``danger`` marks the accept button."""

    def __init__(self, parent: QWidget | None, title: str, text: str, accept: str, danger: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        heading = QLabel(title)
        heading.setProperty("role", "heading")
        heading.setWordWrap(True)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.accept_button = QPushButton(accept)
        self.accept_button.setProperty("danger", danger)
        self.cancel_button = QPushButton(S.CANCEL)
        self.cancel_button.setDefault(True)
        self.accept_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.accept_button)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addLayout(buttons)
        self.setMinimumWidth(420)

    @staticmethod
    def ask(parent: QWidget | None, title: str, text: str, accept: str = S.CONFIRM, danger: bool = False) -> bool:
        """True when the user accepted. Tests replace this method instead of driving a modal dialog."""
        return ConfirmDialog(parent, title, text, accept, danger).exec() == QDialog.DialogCode.Accepted
