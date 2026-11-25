"""Large tuner display: note name, offset needle and an in-tune colour."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import strings as S
from . import tokens
from .fonts import display_font, ui_font
from .glass import BackdropRoot, GlassPanel
from .icons import icon, pixmap
from .painted import KeyChipButton, PaintedText, SectionLabel

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
        self.setMinimumHeight(110)

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
        base = h - 30  # the labels of the scale live under the baseline
        p.setPen(QPen(tokens.color("tuner-baseline"), 2))
        p.drawLine(margin, base, w - margin, base)
        p.setFont(ui_font(13))
        for step in range(-OFFSET_RANGE, OFFSET_RANGE + 1):
            x = mid + span * step / (2 * OFFSET_RANGE)
            tall = 22 if step == 0 else (14 if step % 7 == 0 else 8)
            p.setPen(QPen(QColor(COLORS["in_tune"]) if step == 0 else tokens.color("tuner-tick"), 3 if step == 0 else 1))
            p.drawLine(int(x), base, int(x), base - tall)
            if step % OFFSET_RANGE == 0:
                p.setPen(tokens.color("text-secondary"))
                p.drawText(QRectF(x - 24, base + 4, 48, 18), Qt.AlignmentFlag.AlignCenter,
                           S.TUNER_SCALE_ZERO if step == 0 else f"{step:+d}".replace("-", "−"))
        if self.state == "none":
            return
        x = mid + span * max(-OFFSET_RANGE, min(OFFSET_RANGE, self.offset)) / (2 * OFFSET_RANGE)
        p.setPen(QPen(QColor(COLORS[self.state]), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        head = base - 38  # a stem standing on the scale with a round head above it
        p.drawLine(int(x), int(head), int(x), base + 2)
        p.setBrush(QColor(COLORS[self.state]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x - 8, head - 8, 16, 16))


class TunerPanel(GlassPanel):
    """Shown in place of the editor while the pedal tuner is on."""

    exit_requested = Signal()

    def __init__(self, root: BackdropRoot) -> None:
        super().__init__(root)
        self.state = "none"
        self.title = SectionLabel(S.TUNER_TITLE, Qt.AlignmentFlag.AlignCenter)
        # texts are painted: the style sheet's global font-size would override QWidget.setFont on labels
        self._note = PaintedText(NO_NOTE, display_font(180, 300))
        self._pill = QWidget()
        self._pill.setObjectName("tunerPill")
        self._pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pill_icon = QLabel()
        self._pill_text = PaintedText("", display_font(18, 600), "text-primary")
        pill_row = QHBoxLayout(self._pill)
        pill_row.setContentsMargins(18, 6, 18, 6)
        pill_row.addWidget(self._pill_icon)
        pill_row.addWidget(self._pill_text)
        self._offset = PaintedText("0", display_font(28, 500))
        hint = QLabel(S.TUNER_HINT)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        hint.setMaximumWidth(560)
        hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.exit_button = KeyChipButton(S.TUNER_EXIT, S.TUNER_KEY)
        self.exit_button.setIcon(icon("x"))
        self.exit_button.setToolTip(S.TUNER_EXIT)
        self.exit_button.clicked.connect(self.exit_requested)
        self.meter = TunerMeter()
        self.meter.setMaximumWidth(620)
        self.meter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.meter.setFixedHeight(110)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        lay.addWidget(self.title)
        lay.addWidget(self._note)
        lay.addWidget(self._pill, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(self._centred(self.meter))
        lay.addWidget(self._offset)
        lay.addLayout(self._centred(hint))
        lay.addSpacing(8)
        lay.addWidget(self.exit_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self.show_reading(None, 0)

    @staticmethod
    def _centred(widget: QWidget) -> QHBoxLayout:
        """A row that centres ``widget`` (a word-wrapped label or the meter needs the width, not an alignment)."""
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(widget, stretch=4)
        row.addStretch(1)
        return row

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
        self._note.setColor(color)
        self._pill_text.setText(S.tuner_status(note, offset))
        icon_name = {"none": "info", "in_tune": "check"}.get(self.state, "arrowUp" if offset < 0 else "arrowDown")
        self._pill_icon.setPixmap(pixmap(icon_name, color, 20))
        self._pill.setProperty("state", self.state)
        self._pill.style().unpolish(self._pill)
        self._pill.style().polish(self._pill)
        self.meter.set_reading(offset, self.state)
