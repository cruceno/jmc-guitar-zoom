"""Confirmation dialog used for every destructive or pedal-writing question, on glass over a dimmed window."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import strings as S
from . import tokens
from .glass import paint_glass
from .icons import pixmap


class Scrim(QWidget):
    """Covers the whole window behind a dialog with the scrim colour (62 % near-black)."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setObjectName("scrim")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setGeometry(window.rect())

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        QPainter(self).fillRect(self.rect(), tokens.color("scrim"))


class ConfirmDialog(QDialog):
    """Title, message and two buttons; Cancel is the default and Escape. ``danger`` marks the accept button.

    It is a frameless glass window (the softened backdrop of the main window under a 96 % tint, gradient rim) and,
    while it is open, a scrim dims the window that asked.
    """

    RADIUS = 16

    def __init__(self, parent: QWidget | None, title: str, text: str, accept: str, danger: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("confirmDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._scrim: Scrim | None = None
        heading = QLabel(title)
        heading.setProperty("role", "heading")
        heading.setWordWrap(True)
        self.title_icon = QLabel()  # a warning mark before the title of a destructive question
        self.title_icon.setPixmap(pixmap("alert", tokens.color("status-warn").name(), 24))
        self.title_icon.setVisible(danger)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(self.title_icon)
        title_row.addWidget(heading, stretch=1)
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
        buttons.addWidget(self.accept_button)  # the destructive choice first, Cancel (the default) last
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)
        layout.addLayout(title_row)
        layout.addWidget(body)
        layout.addSpacing(6)
        layout.addLayout(buttons)
        self.setMinimumWidth(460)

    def _root(self):
        window = self.parentWidget().window() if self.parentWidget() is not None else None
        return getattr(window, "backdrop_root", None)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        root = self._root()
        origin = None
        if root is not None:  # the slice of the softened backdrop under the dialog's place on the screen
            origin = QPointF(root.mapFromGlobal(self.mapToGlobal(self.rect().topLeft())))
        p = QPainter(self)
        paint_glass(p, self.size(), self.RADIUS, "glass-tint-overlay", root, origin)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            window = parent.window()
            self.adjustSize()
            self.move(window.mapToGlobal(window.rect().center()) - self.rect().center())
            if self._scrim is None:
                self._scrim = Scrim(window)
            self._scrim.setGeometry(window.rect())
            self._scrim.show()
            self._scrim.raise_()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._scrim is not None:
            self._scrim.hide()
            self._scrim.deleteLater()
            self._scrim = None
        super().hideEvent(event)

    @staticmethod
    def ask(parent: QWidget | None, title: str, text: str, accept: str = S.CONFIRM, danger: bool = False) -> bool:
        """True when the user accepted. Tests replace this method instead of driving a modal dialog."""
        return ConfirmDialog(parent, title, text, accept, danger).exec() == QDialog.DialogCode.Accepted
