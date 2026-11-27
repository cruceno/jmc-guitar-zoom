"""«Afinación y octavación»: a tuner and a guided intonation assistant that listen to a sound-card input.

The screen replaces the editor like the pedal tuner does, but it needs no pedal: samples from
``AudioInput`` go through a ``PitchTracker``; its readings drive the live tuner, the level meter and an
``IntonationSession`` (the open string, then the same string fretted at the 12th, then the verdict). The
result of every string is drawn on a bridge seen from above, with an arrow for the way its saddle must move.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from jmc_guitar_zoom.audio.capture import AudioInput, InputDevice, list_input_devices
from jmc_guitar_zoom.audio.intonation import (ORDER, Event, IntonationSession, ReferenceKind, Step, Verdict,
                                              saddle_shift_mm, verdict)
from jmc_guitar_zoom.audio.pitch import PitchReading, PitchTracker

from . import settings as settings_module
from . import strings as S
from . import tokens
from .fonts import display_font, ui_font
from .glass import BackdropRoot, GlassPanel
from .icons import icon
from .painted import KeyChipButton, PaintedText, SectionLabel
from .settings import IntonationStore

LOW_LEVEL_DB = -40.0  # a note quieter than this peak asks for more gain
METER_FLOOR_DB = -60.0
CLIP_HOLD_SECONDS = 1.5  # the clipping warning outlives the hop that raised it
DETUNED_CENTS = 5.0  # a reference this far from its note is worth tuning before measuring
METER_RANGE = 50.0  # the live meter spans ±50 cents
NEAR_CENTS = 5.0
REFERENCE_KINDS = (ReferenceKind.OPEN, ReferenceKind.HARMONIC)  # the reference buttons' ids, in order

VERDICT_TOKEN = {Verdict.OK: "status-ok", Verdict.SHARP: "status-danger", Verdict.FLAT: "status-warn"}
ARROW_OF = {Verdict.OK: "ok", Verdict.SHARP: "down", Verdict.FLAT: "up"}  # up: toward the neck


class LevelMeter(QWidget):
    """Peak level of the input, -60..0 dBFS, red while it clips."""

    def __init__(self) -> None:
        super().__init__()
        self.level_db = METER_FLOOR_DB
        self.clipping = False
        self.setFixedSize(150, 14)
        self.setAccessibleName(S.INTONATION_DEVICE)

    def set_level(self, level_db: float, clipping: bool) -> None:
        self.level_db, self.clipping = max(METER_FLOOR_DB, min(0.0, level_db)), clipping
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(self.rect()).adjusted(0.5, 3.5, -0.5, -3.5)
        p.setPen(QPen(tokens.color("border-control"), 1))
        p.setBrush(tokens.color("surface-sunken"))
        p.drawRoundedRect(track, 3, 3)
        fill = (self.level_db - METER_FLOOR_DB) / -METER_FLOOR_DB
        if fill > 0:
            token = "status-danger" if self.clipping else ("status-warn" if self.level_db < LOW_LEVEL_DB
                                                           else "status-ok")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tokens.color(token))
            p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * fill, track.height()), 3, 3)


class CentsMeter(QWidget):
    """A ±50 cent scale with a tick every 5 cents and a needle at the current reading."""

    def __init__(self) -> None:
        super().__init__()
        self.cents: float | None = None
        self.tolerance = 1.0
        self.setMinimumHeight(80)

    @property
    def state(self) -> str:
        if self.cents is None:
            return "none"
        if abs(self.cents) <= self.tolerance:
            return "in_tune"
        return "near" if abs(self.cents) <= NEAR_CENTS else "off"

    def set_reading(self, cents: float | None, tolerance: float) -> None:
        self.cents, self.tolerance = cents, tolerance
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 26
        span = w - 2 * margin
        base = h - 24
        x_of = lambda c: margin + span * (c + METER_RANGE) / (2 * METER_RANGE)  # noqa: E731
        p.setPen(QPen(tokens.color("tuner-baseline"), 2))
        p.drawLine(margin, base, w - margin, base)
        p.setFont(ui_font(12))
        for step in range(-10, 11):
            cents = step * 5
            x = x_of(cents)
            tall = 20 if cents == 0 else (13 if cents % 25 == 0 else 7)
            p.setPen(QPen(tokens.color("tuner-in-tune" if cents == 0 else "tuner-tick"), 3 if cents == 0 else 1))
            p.drawLine(int(x), base, int(x), base - tall)
            if cents % 25 == 0:
                p.setPen(tokens.color("text-secondary"))
                label = "0" if cents == 0 else f"{cents:+d}".replace("-", S.MINUS)
                p.drawText(QRectF(x - 24, base + 4, 48, 16), Qt.AlignmentFlag.AlignCenter, label)
        if self.cents is None:
            return
        color = tokens.color({"in_tune": "tuner-in-tune", "near": "tuner-near", "off": "tuner-off"}[self.state])
        x = x_of(max(-METER_RANGE, min(METER_RANGE, self.cents)))
        head = base - 34
        p.setPen(QPen(color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(x), int(head), int(x), base + 2)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x - 7, head - 7, 14, 14))


class BridgeView(QWidget):
    """A guitar bridge seen from above, the neck toward the top: six strings, six saddles and one arrow each.

    A string measured flat at the 12th fret gets an arrow toward the neck (move the saddle closer), a sharp
    one an arrow away from it, an in-tolerance one a check mark; the arrow grows with the offset.
    """

    MIN_ARROW = 14
    MAX_ARROW = 46
    FULL_SCALE_CENTS = 10.0  # the arrow reaches its full length at this offset
    SADDLE_W = 28
    SADDLE_H = 20
    STAGGER = {6: 9, 5: 6, 4: 3, 3: 0, 2: 0, 1: -3}  # the bass saddles sit further from the neck

    def __init__(self) -> None:
        super().__init__()
        self.active_string: int | None = None
        self._results: dict[int, tuple[float, Verdict]] = {}
        self.setMinimumSize(460, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(S.INTONATION_BRIDGE_NAME)

    # -- state

    def set_results(self, results: dict[int, tuple[float, Verdict]], active: int | None) -> None:
        self._results = dict(results)
        self.active_string = active
        self.update()

    def arrow(self, number: int) -> str | None:
        """"up" (toward the neck), "down" (away from it), "ok" or None for a string not measured."""
        result = self._results.get(number)
        return None if result is None else ARROW_OF[result[1]]

    def arrow_length(self, number: int) -> float:
        result = self._results.get(number)
        if result is None or result[1] is Verdict.OK:
            return 0.0
        share = min(1.0, abs(result[0]) / self.FULL_SCALE_CENTS)
        return self.MIN_ARROW + (self.MAX_ARROW - self.MIN_ARROW) * share

    def offset_label(self, number: int) -> str:
        result = self._results.get(number)
        return "" if result is None else S.decimal(result[0], 1, signed=True)

    # -- painting

    def _geometry(self) -> tuple[QRectF, dict[int, QPointF]]:
        width = min(self.width() - 24, 760)
        left = (self.width() - width) / 2
        top = 56
        plate = QRectF(left, top, width, max(60, self.height() - top - 34))
        slot = width / len(ORDER)
        centres = {n: QPointF(left + slot * (i + 0.5), plate.top() + plate.height() * 0.46 + self.STAGGER[n])
                   for i, n in enumerate(ORDER)}
        return plate, centres

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        plate, centres = self._geometry()
        # the neck direction, above the strings
        p.setPen(tokens.color("text-secondary"))
        p.setFont(ui_font(13, QFont.Weight.Medium))
        mid = self.width() / 2
        p.drawText(QRectF(mid - 110, 6, 220, 18), Qt.AlignmentFlag.AlignCenter, S.INTONATION_BRIDGE_NECK)
        p.setPen(QPen(tokens.color("text-secondary"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(mid - 8, 38), QPointF(mid, 30), QPointF(mid + 8, 38)]))
        # the plate with its two posts
        body = QPainterPath()
        body.addRoundedRect(plate, 14, 14)
        p.setPen(QPen(tokens.color("border-control"), 1.5))
        p.setBrush(tokens.color("surface-raised"))
        p.drawPath(body)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tokens.color("surface-sunken"))
        for x in (plate.left() + 14, plate.right() - 14):
            p.drawEllipse(QPointF(x, plate.bottom() - 14), 5, 5)
        # strings, saddles, marks and labels
        for number, centre in centres.items():
            active = number == self.active_string
            self._paint_string(p, number, centre, plate, active)
        for number, centre in centres.items():
            self._paint_saddle(p, number, centre, number == self.active_string)
        for number, centre in centres.items():
            self._paint_mark(p, number, centre)
        for number, centre in centres.items():
            active = number == self.active_string
            p.setPen(tokens.color("accent" if active else "text-secondary"))
            p.setFont(ui_font(13, QFont.Weight.Bold if active else QFont.Weight.Normal))
            p.drawText(QRectF(centre.x() - 40, plate.bottom() + 6, 80, 20), Qt.AlignmentFlag.AlignCenter,
                       S.string_chip(number))

    def _paint_string(self, p: QPainter, number: int, centre: QPointF, plate: QRectF, active: bool) -> None:
        color = tokens.color("accent" if active else "text-tertiary")
        p.setPen(QPen(color, 3 if active else 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawLine(QPointF(centre.x(), 44), QPointF(centre.x(), plate.bottom() - 6))

    def _paint_saddle(self, p: QPainter, number: int, centre: QPointF, active: bool) -> None:
        rect = QRectF(centre.x() - self.SADDLE_W / 2, centre.y() - self.SADDLE_H / 2, self.SADDLE_W, self.SADDLE_H)
        p.setPen(QPen(tokens.color("accent" if active else "border-strong"), 2.5 if active else 1.5))
        p.setBrush(tokens.color("surface-control-hover" if active else "surface-control"))
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(QPen(tokens.color("text-tertiary"), 1))
        p.drawLine(QPointF(rect.left() + 6, centre.y()), QPointF(rect.right() - 6, centre.y()))

    def _paint_mark(self, p: QPainter, number: int, centre: QPointF) -> None:
        kind = self.arrow(number)
        if kind is None:
            return
        color = tokens.color(VERDICT_TOKEN[self._results[number][1]])
        pen = QPen(color, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(color)
        top, bottom = centre.y() - self.SADDLE_H / 2, centre.y() + self.SADDLE_H / 2
        x = centre.x()
        if kind == "ok":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(x - 10, top - 14), QPointF(x - 3, top - 7), QPointF(x + 10, top - 24)]))
        else:
            length = self.arrow_length(number)
            sign = -1 if kind == "up" else 1
            start_y = top if kind == "up" else bottom
            tip_y = start_y + sign * length
            p.drawLine(QPointF(x, start_y), QPointF(x, tip_y - sign * 4))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF([QPointF(x, tip_y), QPointF(x - 8, tip_y - sign * 11),
                                     QPointF(x + 8, tip_y - sign * 11)]))
        p.setPen(color)
        p.setFont(ui_font(13, QFont.Weight.Medium))
        p.drawText(QRectF(centre.x() + self.SADDLE_W / 2 + 5, centre.y() - 10, 52, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.offset_label(number))


class IntonationScreen(GlassPanel):
    """Shown in place of the editor: the input choice, the live tuner, the guided steps and the bridge."""

    exit_requested = Signal()

    def __init__(self, root: BackdropRoot, *, devices=None, audio=None, store: IntonationStore | None = None) -> None:
        super().__init__(root)
        self._list_devices = devices if devices is not None else list_input_devices
        self.audio = audio if audio is not None else AudioInput(self)
        self.store = store if store is not None else IntonationStore(settings_module.intonation_path())
        self.session = IntonationSession(tolerance=self.store.tolerance,
                                         reference_kind=ReferenceKind(self.store.reference))
        self.scale_mm = self.store.scale_mm
        self._devices: list[InputDevice] = []
        self._tracker: PitchTracker | None = None
        self._loading = False
        self._clip_until = -1.0
        self._message = ""
        self._build()
        self.audio.samples.connect(self._on_samples)
        self.audio.failed.connect(self._on_failed)
        self._refresh()

    # ------------------------------------------------------------------ construction

    def _build(self) -> None:
        self.title = SectionLabel(S.INTONATION_TITLE, Qt.AlignmentFlag.AlignLeft)
        self.exit_button = KeyChipButton(S.INTONATION_EXIT, S.INTONATION_KEY)
        self.exit_button.setIcon(icon("x"))
        self.exit_button.setToolTip(S.INTONATION_EXIT)
        self.exit_button.clicked.connect(self.exit_requested)
        top = QHBoxLayout()
        top.addWidget(self.title, stretch=1)
        top.addWidget(self.exit_button)

        self.device_combo = QComboBox()
        self.device_combo.setAccessibleName(S.INTONATION_DEVICE)
        self.device_combo.setMinimumWidth(220)
        self.channel_combo = QComboBox()
        self.channel_combo.setAccessibleName(S.INTONATION_CHANNEL)
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(icon("reload"))
        self.refresh_button.setToolTip(S.INTONATION_REFRESH)
        self.refresh_button.setAccessibleName(S.INTONATION_REFRESH)
        self.refresh_button.setProperty("icon-only", True)
        self.level_meter = LevelMeter()
        self._level_label = self._text_label("reason")
        device_row = QHBoxLayout()
        device_row.setSpacing(10)
        for w in (self.device_combo, self.channel_combo, self.refresh_button, self.level_meter):
            device_row.addWidget(w)
        device_row.addWidget(self._level_label, stretch=1)
        self._status = self._text_label("reason")

        # live tuner
        self._note = PaintedText(S.INTONATION_NO_NOTE, display_font(64, 300))
        self._cents = PaintedText("", display_font(26, 500))
        self._frequency = PaintedText("", ui_font(16), "text-secondary")
        self._stable = PaintedText("", display_font(16, 600), "tuner-in-tune")
        self.meter = CentsMeter()
        tuner = QVBoxLayout()
        tuner.addStretch(1)
        for w in (self._note, self._cents, self._frequency, self.meter, self._stable):
            tuner.addWidget(w)
        tuner.addStretch(1)

        self.assistant_box = self._build_assistant()
        body = QHBoxLayout()
        body.setSpacing(24)
        body.addLayout(tuner, stretch=5)
        body.addWidget(self.assistant_box, stretch=6)

        self.bridge = BridgeView()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 14, 24, 14)
        lay.setSpacing(8)
        lay.addLayout(top)
        lay.addLayout(device_row)
        lay.addWidget(self._status)
        lay.addLayout(body, stretch=1)
        lay.addWidget(self.bridge, stretch=1)

        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        self.refresh_button.clicked.connect(self._on_refresh)

    @staticmethod
    def _text_label(role: str) -> QLabel:
        label = QLabel("")
        label.setWordWrap(True)
        label.setProperty("role", role)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        return label

    def _build_assistant(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        # the six strings
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.string_chips: dict[int, QPushButton] = {}
        # buttons report through their group's id to bound methods: a lambda capturing self in a child's signal
        # makes a reference cycle that PySide tears down after Qt at interpreter exit (a segfault on exit)
        group = QButtonGroup(box)
        group.setExclusive(True)
        for number in ORDER:
            chip = QPushButton(S.string_chip(number))
            chip.setCheckable(True)
            chip.setProperty("chip", True)
            group.addButton(chip, number)
            chips.addWidget(chip)
            self.string_chips[number] = chip
        group.idClicked.connect(self._select)
        # the options
        self.open_button = QPushButton(S.INTONATION_REFERENCE_OPEN)
        self.harmonic_button = QPushButton(S.INTONATION_REFERENCE_HARMONIC)
        references = QButtonGroup(box)
        references.setExclusive(True)
        for index, (kind, button) in enumerate(zip(REFERENCE_KINDS, (self.open_button, self.harmonic_button))):
            button.setCheckable(True)
            button.setChecked(self.session.reference_kind is kind)
            references.addButton(button, index)
        references.idClicked.connect(self._on_reference_id)
        self.tolerance_combo = self._combo(S.INTONATION_TOLERANCES, self.session.tolerance, S.INTONATION_TOLERANCE)
        self.scale_combo = self._combo(S.INTONATION_SCALES, self.scale_mm, S.INTONATION_SCALE)
        self.tolerance_combo.currentIndexChanged.connect(self._on_tolerance)
        self.scale_combo.currentIndexChanged.connect(self._on_scale)
        options = QHBoxLayout()
        options.setSpacing(8)
        for w in (self.open_button, self.harmonic_button):
            options.addWidget(w)
        options.addStretch(1)
        options.addWidget(self._caption(S.INTONATION_TOLERANCE))
        options.addWidget(self.tolerance_combo)
        options.addWidget(self._caption(S.INTONATION_SCALE))
        options.addWidget(self.scale_combo)
        # the steps and the capture progress
        self.step_labels = [QLabel(text) for text in S.INTONATION_STEPS]
        steps = QHBoxLayout()
        for label in self.step_labels:
            label.setProperty("role", "step")
            steps.addWidget(label)
        steps.addStretch(1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self._instruction = self._text_label("instruction")
        self._message_label = self._text_label("notice")
        self._info = self._text_label("reason")
        self.remeasure_button = QPushButton(S.INTONATION_REMEASURE)
        self.remeasure_button.setIcon(icon("reset"))
        self.remeasure_button.clicked.connect(self._on_remeasure)
        self.next_button = QPushButton(S.INTONATION_NEXT)
        self.next_button.clicked.connect(self._on_next)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remeasure_button)
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        self._hint = self._text_label("hint")
        self._hint.setText(S.INTONATION_HINT)
        lay.addLayout(chips)
        lay.addLayout(options)
        lay.addLayout(steps)
        lay.addWidget(self.progress_bar)
        for w in (self._instruction, self._message_label, self._info):
            lay.addWidget(w)
        lay.addLayout(buttons)
        lay.addWidget(self._hint)
        lay.addStretch(1)
        return box

    @staticmethod
    def _combo(items, current: float, name: str) -> QComboBox:
        combo = QComboBox()
        combo.setAccessibleName(name)
        for text, value in items:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "reason")
        return label

    # ------------------------------------------------------------------ read-only views (tests and callers)

    def note_text(self) -> str:
        return self._note.text()

    def cents_text(self) -> str:
        return self._cents.text()

    def frequency_text(self) -> str:
        return self._frequency.text()

    def stable_text(self) -> str:
        return self._stable.text()

    def level_message(self) -> str:
        return self._level_label.text()

    def status_text(self) -> str:
        return self._status.text()

    def instruction_text(self) -> str:
        return self._instruction.text()

    def message_text(self) -> str:
        return self._message_label.text()

    def info_text(self) -> str:
        return self._info.text()

    def hint_text(self) -> str:
        return self._hint.text()

    def current_step_label(self) -> str:
        return next((label.text() for label in self.step_labels if label.property("current")), "")

    def chip_state(self, number: int) -> str:
        """"pending", "ok", "sharp" or "flat": the last result of the string against the current tolerance."""
        result = self.session.results.get(number)
        return "pending" if result is None else verdict(result.offset, self.session.tolerance).value

    # ------------------------------------------------------------------ opening and closing

    def open_screen(self) -> None:
        """Start listening: list the inputs, restore the remembered choice and open the input."""
        self._load_devices(self.store.device, self.store.channel)
        if self._devices:
            self._restart_audio()
        if self.session.string is None:
            self._select(ORDER[0])
        self._refresh()

    def close_screen(self) -> None:
        self.audio.stop()
        self._tracker = None

    # ------------------------------------------------------------------ input devices

    def _load_devices(self, wanted: str | None, channel: int) -> None:
        self._loading = True
        try:
            self._devices = list(self._list_devices())
            self.device_combo.clear()
            for device in self._devices:
                self.device_combo.addItem(device.name, device.id)
            index = self.device_combo.findData(wanted) if wanted is not None else -1
            found = index >= 0
            self.device_combo.setCurrentIndex(index if found else 0)
            if self._devices:
                self._fill_channels(self._devices[max(index, 0)], channel if found else 0)
            else:
                self.channel_combo.clear()
        finally:
            self._loading = False
        has_input = bool(self._devices)
        self.device_combo.setEnabled(has_input)
        self.channel_combo.setEnabled(has_input)
        self.assistant_box.setEnabled(has_input)
        self._set_status("" if has_input else S.INTONATION_NO_INPUT)

    def _fill_channels(self, device: InputDevice, wanted: int) -> None:
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        for number in range(1, device.channels + 1):
            self.channel_combo.addItem(f"Canal {number}", number - 1)
        self.channel_combo.setCurrentIndex(max(0, min(wanted, device.channels - 1)))
        self.channel_combo.blockSignals(False)

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def _current_device(self) -> InputDevice | None:
        index = self.device_combo.currentIndex()
        return self._devices[index] if 0 <= index < len(self._devices) else None

    def _restart_audio(self) -> None:
        self.audio.stop()
        self._tracker = None
        self._clip_until = -1.0
        device = self._current_device()
        if device is None:
            return
        if self.audio.start(device.id, max(0, self.channel_combo.currentIndex())):
            self._tracker = PitchTracker(self.audio.sample_rate)
            self._set_status("")
        else:
            self._set_status(S.INTONATION_INPUT_FAILED)
        self._show_reading(None)
        self.level_meter.set_level(METER_FLOOR_DB, False)
        self._level_label.setText("")

    def _on_device_changed(self, _index: int) -> None:
        if self._loading:
            return
        device = self._current_device()
        if device is None:
            return
        self._fill_channels(device, 0)
        self.store.save(device=device.id, channel=self.channel_combo.currentIndex())
        self._restart_audio()

    def _on_channel_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self.store.save(channel=index)
        self._restart_audio()

    def _on_refresh(self) -> None:
        device = self._current_device()
        channel = self.channel_combo.currentIndex()
        self._load_devices(device.id if device is not None else None, channel)
        if self._devices and not self.audio.running:
            self._restart_audio()

    def _on_failed(self, _message: str) -> None:
        self._tracker = None
        self._set_status(S.INTONATION_INPUT_FAILED)

    # ------------------------------------------------------------------ readings

    def _on_samples(self, block) -> None:
        if self._tracker is None:
            return
        reading = self._tracker.feed(block)
        if reading is not None:
            self._on_reading(reading)

    def _on_reading(self, reading: PitchReading) -> None:
        self._show_reading(reading)
        self._show_level(reading)
        if self.assistant_box.isEnabled():
            self._on_event(self.session.feed(reading))
        self.progress_bar.setValue(round(self.session.progress * 100))

    def _show_reading(self, reading: PitchReading | None) -> None:
        if reading is None or reading.frequency is None:
            self._note.setText(S.INTONATION_NO_NOTE)
            self._cents.setText("")
            self._frequency.setText("")
            self._stable.setText("")
            self.meter.set_reading(None, self.session.tolerance)
            return
        self._note.setText(f"{reading.note}{reading.octave}")
        self._cents.setText(S.intonation_cents(reading.cents))
        self._frequency.setText(S.intonation_hz(reading.frequency))
        self._stable.setText(S.INTONATION_STABLE if reading.stable else "")
        self.meter.set_reading(reading.cents, self.session.tolerance)
        color = {"in_tune": "tuner-in-tune", "near": "tuner-near", "off": "tuner-off"}[self.meter.state]
        self._note.setColor(color)

    def _show_level(self, reading: PitchReading) -> None:
        self.level_meter.set_level(reading.level_db, reading.clipping)
        if reading.clipping:
            self._clip_until = reading.time + CLIP_HOLD_SECONDS
        if reading.time < self._clip_until:
            text = S.INTONATION_CLIPPING
        elif reading.frequency is not None and reading.level_db < LOW_LEVEL_DB:
            text = S.INTONATION_LOW_LEVEL
        else:
            text = ""
        self._level_label.setProperty("blocking", text == S.INTONATION_CLIPPING)
        self._level_label.style().unpolish(self._level_label)
        self._level_label.style().polish(self._level_label)
        self._level_label.setText(text)

    def _on_event(self, event: Event | None) -> None:
        string = self.session.string
        if event is Event.NOT_THE_OCTAVE:
            self._message = S.intonation_not_octave(self.session.reference_kind.value, string)
        elif event is not None:
            self._message = ""
        elif self.session.progress > 0:
            self._message = ""  # a note that is being captured is the right one
        if event is not None or self._message != self._message_label.text():
            self._refresh()

    # ------------------------------------------------------------------ the assistant

    def _select(self, number: int) -> None:
        self.session.select(number)
        self._message = ""
        self._refresh()

    def _on_remeasure(self) -> None:
        self.session.remeasure()
        self._message = ""
        self._refresh()

    def _on_next(self) -> None:
        number = self.session.next_string()
        if number is None:
            self._message = S.INTONATION_ALL_OK
            self._refresh()
        else:
            self._select(number)

    def _on_reference_id(self, index: int) -> None:
        self._on_reference(REFERENCE_KINDS[index])

    def _on_reference(self, kind: ReferenceKind) -> None:
        self.session.reference_kind = kind
        self.store.save(reference=kind.value)
        self._on_remeasure()

    def _on_tolerance(self, index: int) -> None:
        self.session.tolerance = float(self.tolerance_combo.itemData(index))
        self.store.save(tolerance=self.session.tolerance)
        self._refresh()

    def _on_scale(self, index: int) -> None:
        self.scale_mm = float(self.scale_combo.itemData(index))
        self.store.save(scale_mm=self.scale_mm)
        self._refresh()

    def _instruction_text(self) -> str:
        session = self.session
        if session.string is None or session.step is None:
            return ""
        if session.step is Step.RESULT:
            result = session.results[session.string]
            return S.intonation_result(verdict(result.offset, session.tolerance).value, session.string,
                                       result.offset, saddle_shift_mm(result.offset, self.scale_mm))
        return S.intonation_instruction(session.step.value, session.reference_kind.value, session.string)

    def _refresh(self) -> None:
        """Everything the session state decides: chips, steps, texts and the bridge."""
        session = self.session
        steps = {Step.REFERENCE: 0, Step.FRETTED: 1, Step.RESULT: 2}
        current = steps.get(session.step)
        for i, label in enumerate(self.step_labels):
            label.setProperty("current", i == current)
            label.style().unpolish(label)
            label.style().polish(label)
        for number, chip in self.string_chips.items():
            state = self.chip_state(number)
            chip.setChecked(number == session.string)
            chip.setProperty("result", state)
            chip.setAccessibleName(S.string_chip_name(number, None if state == "pending" else state))
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        self._instruction.setText(self._instruction_text())
        self._message_label.setText(self._message)
        self._message_label.setVisible(bool(self._message))
        detuned = (session.step in (Step.FRETTED, Step.RESULT) and session.reference_detune is not None
                   and abs(session.reference_detune) > DETUNED_CENTS)
        self._info.setText(S.intonation_detuned(session.reference_detune) if detuned else "")
        self._info.setVisible(detuned)
        self.progress_bar.setValue(round(session.progress * 100))
        self.bridge.set_results({n: (r.offset, verdict(r.offset, session.tolerance))
                                 for n, r in session.results.items()}, session.string)
