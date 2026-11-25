"""Large tuner display: note name, offset needle and an in-tune colour."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from . import strings as S

NO_NOTE = "—"
OFFSET_RANGE = 7  # the pedal reports offsets -7..+7 (CC 99 value - 8)
COLORS = {"in_tune": "#2ecc71", "near": "#f1c40f", "off": "#e74c3c", "none": "#8a8d93"}


def tuner_state(note: str | None, offset: int) -> str:
    """"none" without a note, "in_tune" at offset 0, "near" within 2 steps, else "off"."""
    if note is None:
        return "none"
    if offset == 0:
        return "in_tune"
    return "near" if abs(offset) <= 2 else "off"


class TunerMeter(QWidget):
    """Horizontal scale with a needle at the current offset."""

    def __init__(self) -> None:
        super().__init__()
        self.offset = 0
        self.state = "none"
        self.setMinimumHeight(90)

    def set_reading(self, offset: int, state: str) -> None:
        self.offset, self.state = offset, state
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 30
        span = w - 2 * margin
        mid = w / 2
        p.setPen(QPen(QColor("#555a62"), 2))
        p.drawLine(margin, h - 20, w - margin, h - 20)
        for step in range(-OFFSET_RANGE, OFFSET_RANGE + 1):
            x = mid + span * step / (2 * OFFSET_RANGE)
            tall = 22 if step == 0 else (14 if step % 7 == 0 else 8)
            p.setPen(QPen(QColor(COLORS["in_tune"]) if step == 0 else QColor("#8a8d93"), 3 if step == 0 else 1))
            p.drawLine(int(x), h - 20, int(x), h - 20 - tall)
        if self.state == "none":
            return
        x = mid + span * max(-OFFSET_RANGE, min(OFFSET_RANGE, self.offset)) / (2 * OFFSET_RANGE)
        p.setPen(QPen(QColor(COLORS[self.state]), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(x), 8, int(x), h - 18)
        p.setBrush(QColor(COLORS[self.state]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x - 7, h - 27, 14, 14))


class TunerPanel(QWidget):
    """Shown in place of the editor while the pedal tuner is on."""

    def __init__(self) -> None:
        super().__init__()
        self.state = "none"
        self._note = QLabel(NO_NOTE)
        self._note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(120)
        font.setBold(True)
        self._note.setFont(font)
        self._offset = QLabel("0")
        self._offset.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._offset.setStyleSheet("font-size: 28px;")
        hint = QLabel(S.TUNER_HINT)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #8a8d93;")
        self.meter = TunerMeter()
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        for w in (self._note, self.meter, self._offset, hint):
            lay.addWidget(w)
        lay.addStretch(1)
        self.show_reading(None, 0)

    def note_text(self) -> str:
        return self._note.text()

    def offset_text(self) -> str:
        return self._offset.text()

    def show_reading(self, note: str | None, offset: int) -> None:
        self.state = tuner_state(note, offset)
        self._note.setText(note if note is not None else NO_NOTE)
        self._offset.setText(NO_NOTE if note is None else ("0" if offset == 0 else f"{offset:+d}"))
        color = COLORS[self.state]
        self._note.setStyleSheet(f"color: {color};")
        self.meter.set_reading(offset, self.state)
