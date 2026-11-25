"""Large tuner display: note name, offset needle and an in-tune colour."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import strings as S
from . import tokens
from .fonts import display_font
from .glass import BackdropRoot, GlassPanel
from .icons import pixmap

NO_NOTE = "—"
OFFSET_RANGE = 7  # the pedal reports offsets -7..+7 (CC 99 value - 8)
COLORS = {"in_tune": tokens.color("tuner-in-tune").name(), "near": tokens.color("tuner-near").name(),
          "off": tokens.color("tuner-off").name(), "none": tokens.color("tuner-tick").name()}


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
        p.setPen(QPen(tokens.color("tuner-baseline"), 2))
        p.drawLine(margin, h - 20, w - margin, h - 20)
        for step in range(-OFFSET_RANGE, OFFSET_RANGE + 1):
            x = mid + span * step / (2 * OFFSET_RANGE)
            tall = 22 if step == 0 else (14 if step % 7 == 0 else 8)
            p.setPen(QPen(QColor(COLORS["in_tune"]) if step == 0 else tokens.color("tuner-tick"), 3 if step == 0 else 1))
            p.drawLine(int(x), h - 20, int(x), h - 20 - tall)
        if self.state == "none":
            return
        x = mid + span * max(-OFFSET_RANGE, min(OFFSET_RANGE, self.offset)) / (2 * OFFSET_RANGE)
        p.setPen(QPen(QColor(COLORS[self.state]), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(x), 8, int(x), h - 18)
        p.setBrush(QColor(COLORS[self.state]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x - 7, h - 27, 14, 14))


class TunerPanel(GlassPanel):
    """Shown in place of the editor while the pedal tuner is on."""

    def __init__(self, root: BackdropRoot) -> None:
        super().__init__(root)
        self.state = "none"
        self._note = QLabel(NO_NOTE)
        self._note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._note.setFont(display_font(180, 300))
        self._pill = QWidget()
        self._pill.setObjectName("tunerPill")
        self._pill_icon = QLabel()
        self._pill_text = QLabel("")
        self._pill_text.setFont(display_font(18, 600))
        pill_row = QHBoxLayout(self._pill)
        pill_row.setContentsMargins(18, 6, 18, 6)
        pill_row.addWidget(self._pill_icon)
        pill_row.addWidget(self._pill_text)
        self._offset = QLabel("0")
        self._offset.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._offset.setFont(display_font(28, 500))
        hint = QLabel(S.TUNER_HINT)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setProperty("role", "secondary")
        self.meter = TunerMeter()
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        lay.addWidget(self._note)
        lay.addWidget(self._pill, alignment=Qt.AlignmentFlag.AlignHCenter)
        for w in (self.meter, self._offset, hint):
            lay.addWidget(w)
        lay.addStretch(1)
        self.show_reading(None, 0)

    def note_text(self) -> str:
        return self._note.text()

    def status_text(self) -> str:
        return self._pill_text.text()

    def offset_text(self) -> str:
        return self._offset.text()

    def show_reading(self, note: str | None, offset: int) -> None:
        self.state = tuner_state(note, offset)
        self._note.setText(note if note is not None else NO_NOTE)
        self._offset.setText(NO_NOTE if note is None else ("0" if offset == 0 else f"{offset:+d}"))
        color = COLORS[self.state]
        self._note.setStyleSheet(f"color: {color};")
        self._pill_text.setText(S.tuner_status(note, offset))
        icon_name = {"none": "info", "in_tune": "check"}.get(self.state, "arrowUp" if offset < 0 else "arrowDown")
        self._pill_icon.setPixmap(pixmap(icon_name, color, 20))
        self._pill.setProperty("state", self.state)
        self._pill.style().unpolish(self._pill)
        self._pill.style().polish(self._pill)
        self.meter.set_reading(offset, self.state)
