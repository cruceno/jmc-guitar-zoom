"""«Calibración»: four steps (neck relief, action, pickups, intonation) around a tuner that listens to a sound card.

The screen replaces the editor like the pedal tuner does, but it needs no pedal. The input bar and the live tuner
stay for every step; steps 1 to 3 live in ``calibration.py``. Step 4 is the intonation assistant: samples from
``AudioInput`` go through a ``PitchTracker``; its readings drive the live tuner, the level meter and an
``IntonationSession`` (rounds of the open string, the 12th-fret harmonic and the fretted 12th, then a verdict
from the mean offset and its confidence interval). The result of every string is drawn on a bridge seen from
above, with an arrow for the way its saddle must move.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from jmc_guitar_zoom.audio.capture import AudioInput, InputDevice, list_input_devices
from jmc_guitar_zoom.audio.intonation import (MAX_ROUNDS, MIN_ROUNDS, ORDER, Event, IntonationSession, Stats, Step,
                                              Verdict, mean_interval, saddle_shift_mm)
from jmc_guitar_zoom.audio.pitch import PitchReading, PitchTracker

from . import settings as settings_module
from . import strings as S
from . import tokens
from .fonts import display_font, ui_font
from .calibration import ActionPanel, PickupsPanel, PresetRow, ReliefPanel, StepBar
from .glass import BackdropRoot, GlassPanel
from .icons import icon
from .painted import KeyChipButton, PaintedText, SectionLabel
from .settings import CalibrationStore, IntonationStore

LOW_LEVEL_DB = -40.0  # a note quieter than this peak asks for more gain
METER_FLOOR_DB = -60.0
CLIP_HOLD_SECONDS = 1.5  # the clipping warning outlives the hop that raised it
DETUNED_CENTS = 5.0  # a reference this far from its note is worth tuning before measuring
METER_RANGE = 50.0  # the live meter spans ±50 cents
NEAR_CENTS = 5.0

VERDICT_TOKEN = {Verdict.OK: "status-ok", Verdict.SHARP: "status-danger", Verdict.FLAT: "status-warn",
                 Verdict.UNSURE: "status-info"}
ARROW_OF = {Verdict.OK: "ok", Verdict.SHARP: "down", Verdict.FLAT: "up", Verdict.UNSURE: "unsure"}  # up: toward the neck


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
    one an arrow away from it, an in-tolerance one a check mark and a not conclusive one a «?»; the arrow grows
    with the offset.
    """

    MIN_ARROW = 14
    MAX_ARROW = 46
    FULL_SCALE_CENTS = 10.0  # the arrow reaches its full length at this offset
    SADDLE_W = 28
    SADDLE_H = 20
    UNSURE_RADIUS = 15  # the «?» mark of a not conclusive string
    UNSURE_DX = 22  # its centre sits this far to the left of the string, so the string line never crosses it
    STAGGER = {6: 9, 5: 6, 4: 3, 3: 0, 2: 0, 1: -3}  # the bass saddles sit further from the neck

    def __init__(self) -> None:
        super().__init__()
        self.active_string: int | None = None
        self._results: dict[int, tuple[float, Verdict]] = {}
        self.setMinimumSize(460, 186)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(S.INTONATION_BRIDGE_NAME)

    # -- state

    def set_results(self, results: dict[int, tuple[float, Verdict]], active: int | None) -> None:
        self._results = dict(results)
        self.active_string = active
        self.update()

    def arrow(self, number: int) -> str | None:
        """"up" (toward the neck), "down" (away from it), "ok", "unsure" or None for a string not measured."""
        result = self._results.get(number)
        return None if result is None else ARROW_OF[result[1]]

    def arrow_length(self, number: int) -> float:
        result = self._results.get(number)
        if result is None or result[1] in (Verdict.OK, Verdict.UNSURE):
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
        elif kind == "unsure":
            radius = self.UNSURE_RADIUS
            mark = QPointF(x - self.UNSURE_DX, top - radius - 6)
            p.setBrush(tokens.color("surface-raised"))
            p.drawEllipse(mark, radius, radius)
            p.setPen(color)
            p.setFont(ui_font(20, QFont.Weight.Bold))
            p.drawText(QRectF(mark.x() - radius, mark.y() - radius, 2 * radius, 2 * radius),
                       Qt.AlignmentFlag.AlignCenter, "?")
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


class DotPlot(QWidget):
    """One row per comparison, a dot per take, the mean with its 95 % interval as a bar and the ±tolerance band."""

    MIN_RANGE = 5.0  # cents each side of zero, at least
    MAX_RANGE = 50.0

    def __init__(self) -> None:
        super().__init__()
        self._dots: list[tuple[float, ...]] = [() for _ in S.INTONATION_PLOT_ROWS]
        self._intervals: list[tuple[float, float | None] | None] = [None for _ in S.INTONATION_PLOT_ROWS]
        self.tolerance = 1.0
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setAccessibleName(S.INTONATION_PLOT_NAME)

    def set_stats(self, stats: Stats | None, tolerance: float) -> None:
        self.tolerance = tolerance
        rows = () if stats is None else (stats.offsets, stats.vs_open, stats.cross)
        self._dots = [tuple(rows[i]) if rows else () for i in range(len(S.INTONATION_PLOT_ROWS))]
        self._intervals = [mean_interval(values) if values else None for values in self._dots]
        self.update()

    # -- read-only values (tests and callers)

    def row_names(self) -> tuple[str, ...]:
        return S.INTONATION_PLOT_ROWS

    def dots(self, row: int) -> tuple[float, ...]:
        """The cents of each take of the comparison, in round order."""
        return self._dots[row]

    def interval(self, row: int) -> tuple[float, float | None] | None:
        """(mean, half-width of the 95 % interval); the half-width is None under three rounds."""
        return self._intervals[row]

    def _range(self) -> float:
        reach = [self.tolerance]
        for values, interval in zip(self._dots, self._intervals):
            reach += [abs(v) for v in values]
            if interval is not None:
                reach.append(abs(interval[0]) + (interval[1] or 0.0))
        return min(self.MAX_RANGE, max(self.MIN_RANGE, math.ceil(max(reach) * 1.1)))

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = ui_font(12)
        p.setFont(font)
        label_w = max(QFontMetrics(font).horizontalAdvance(name) for name in S.INTONATION_PLOT_ROWS) + 12
        left, right, top, bottom = label_w, self.width() - 14, 6, self.height() - 22
        span = max(1.0, right - left)
        reach = self._range()
        x_of = lambda c: left + span * (max(-reach, min(reach, c)) + reach) / (2 * reach)  # noqa: E731
        row_h = (bottom - top) / len(self._dots)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tokens.color("status-ok-bg"))
        p.drawRect(QRectF(x_of(-self.tolerance), top, x_of(self.tolerance) - x_of(-self.tolerance), bottom - top))
        p.setPen(QPen(tokens.color("tuner-baseline"), 1))
        p.drawLine(QPointF(x_of(0), top), QPointF(x_of(0), bottom))
        p.setPen(tokens.color("text-secondary"))
        for edge, shift, align in ((-reach, 0, Qt.AlignmentFlag.AlignLeft), (0, -40, Qt.AlignmentFlag.AlignHCenter),
                                   (reach, -80, Qt.AlignmentFlag.AlignRight)):
            label = "0" if edge == 0 else f"{edge:+.0f}".replace("-", S.MINUS)
            p.drawText(QRectF(x_of(edge) + shift, bottom + 3, 80, 16), align, label)
        for row, (name, values, interval) in enumerate(zip(S.INTONATION_PLOT_ROWS, self._dots, self._intervals)):
            mid = top + row_h * (row + 0.5)
            p.setPen(tokens.color("text-secondary"))
            p.drawText(QRectF(0, mid - 9, label_w - 8, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       name)
            if interval is not None and interval[1] is not None:
                p.setPen(QPen(tokens.color("status-info"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                p.drawLine(QPointF(x_of(interval[0] - interval[1]), mid), QPointF(x_of(interval[0] + interval[1]), mid))
            if interval is not None:
                p.setPen(QPen(tokens.color("text-primary"), 2))
                p.drawLine(QPointF(x_of(interval[0]), mid - 9), QPointF(x_of(interval[0]), mid + 9))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tokens.color("accent"))
            for i, value in enumerate(values):
                p.drawEllipse(QPointF(x_of(value), mid + ((i % 3) - 1) * 4), 3.5, 3.5)


class IntonationScreen(GlassPanel):
    """Shown in place of the editor: the input choice, the live tuner, the guided steps and the bridge."""

    exit_requested = Signal()

    def __init__(self, root: BackdropRoot, *, devices=None, audio=None, store: IntonationStore | None = None,
                 calibration: CalibrationStore | None = None) -> None:
        super().__init__(root)
        self._list_devices = devices if devices is not None else list_input_devices
        self.audio = audio if audio is not None else AudioInput(self)
        self.store = store if store is not None else IntonationStore(settings_module.intonation_path())
        self.calibration = (calibration if calibration is not None
                            else CalibrationStore(settings_module.calibration_path()))
        self._step = self.calibration.step
        self.session = IntonationSession(tolerance=self.store.tolerance, rounds=self.store.rounds)
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
        self.step_bar = StepBar()
        self.step_buttons = self.step_bar.buttons
        top = QHBoxLayout()
        top.addWidget(self.title)
        top.addSpacing(18)
        top.addWidget(self.step_bar, stretch=1)
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
        # the tuner serves every step: centred in step 4, on top with the step's drawing under it in steps 1 to 3
        self._tuner_column = tuner = QVBoxLayout()
        tuner.addStretch(1)
        for w in (self._note, self._cents, self._frequency, self.meter, self._stable):
            tuner.addWidget(w)
        self._tuner_tail = tuner.count()
        tuner.addStretch(1)

        self._order = self._text_label("hint")
        self._order.setText(S.CALIBRATION_ORDER)
        self.preset_row = PresetRow()
        self.preset_combo = self.preset_row.combo
        self.preset_row.set_name(self.calibration.preset)
        self.relief = ReliefPanel(self.calibration)
        self.action = ActionPanel(self.calibration)
        self.pickups = PickupsPanel(self.calibration, self.session.rounds)
        self.assistant_box = self._build_assistant()
        self._pages = {1: self.relief, 2: self.action, 3: self.pickups, 4: self.assistant_box}
        self._drawings = {1: self.relief.drawing, 2: self.action.drawing, 3: self.pickups.drawing}
        for drawing in self._drawings.values():
            tuner.insertWidget(self._tuner_tail, drawing, stretch=1)
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(self.preset_row)
        for page in self._pages.values():
            right.addWidget(page)
        body = QHBoxLayout()
        body.setSpacing(24)
        body.addLayout(tuner, stretch=5)
        body.addLayout(right, stretch=6)

        self.bridge = BridgeView()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 14, 24, 14)
        lay.setSpacing(8)
        lay.addLayout(top)
        lay.addWidget(self._order)
        lay.addLayout(device_row)
        lay.addWidget(self._status)
        lay.addLayout(body, stretch=1)
        lay.addWidget(self.bridge, stretch=1)

        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        self.refresh_button.clicked.connect(self._on_refresh)
        self.step_bar.step_chosen.connect(self.go_to_step)
        self.preset_row.preset_selected.connect(self._on_preset_selected)
        for panel in (self.relief, self.action, self.pickups):
            panel.changed.connect(self._on_calibration_edited)
        self.pickups.rounds_changed.connect(self._on_pickup_rounds)
        self._apply_step()

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
        self.rounds_combo = QComboBox()
        self.rounds_combo.setAccessibleName(S.INTONATION_ROUNDS)
        for n in range(MIN_ROUNDS, MAX_ROUNDS + 1):
            self.rounds_combo.addItem(str(n), n)
        self.rounds_combo.setCurrentIndex(max(0, self.rounds_combo.findData(self.session.rounds)))
        self.tolerance_combo = self._combo(S.INTONATION_TOLERANCES, self.session.tolerance, S.INTONATION_TOLERANCE)
        self.scale_combo = self._combo(S.INTONATION_SCALES, self.scale_mm, S.INTONATION_SCALE)
        self.rounds_combo.currentIndexChanged.connect(self._on_rounds)
        self.tolerance_combo.currentIndexChanged.connect(self._on_tolerance)
        self.scale_combo.currentIndexChanged.connect(self._on_scale)
        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(self._caption(S.INTONATION_ROUNDS))
        options.addWidget(self.rounds_combo)
        options.addStretch(1)
        options.addWidget(self._caption(S.INTONATION_TOLERANCE))
        options.addWidget(self.tolerance_combo)
        options.addWidget(self._caption(S.INTONATION_SCALE))
        options.addWidget(self.scale_combo)
        # the progress line and the capture progress
        self._progress_label = QLabel("")
        self._progress_label.setProperty("role", "step")
        self._progress_label.setProperty("current", True)
        steps = QHBoxLayout()
        steps.addWidget(self._progress_label)
        steps.addStretch(1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self._instruction = self._text_label("instruction")
        self._message_label = self._text_label("notice")
        self._info = self._text_label("reason")
        self._spread = self._text_label("reason")
        self._mean = self._text_label("instruction")
        self._cross = self._text_label("notice")
        self.plot = DotPlot()
        self.repeat_button = QPushButton(S.INTONATION_REPEAT)
        self.repeat_button.clicked.connect(self._on_repeat)
        self.remeasure_button = QPushButton(S.INTONATION_REMEASURE)
        self.remeasure_button.setIcon(icon("reset"))
        self.remeasure_button.clicked.connect(self._on_remeasure)
        self.next_button = QPushButton(S.INTONATION_NEXT)
        self.next_button.clicked.connect(self._on_next)
        buttons = QHBoxLayout()
        buttons.addWidget(self.repeat_button)
        buttons.addWidget(self.remeasure_button)
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        self._reminder = self._text_label("hint")
        self._reminder.setText(S.INTONATION_TOUCH_REMINDER)
        self._hint = self._text_label("hint")
        self._hint.setText(S.INTONATION_HINT)
        lay.addLayout(chips)
        lay.addLayout(options)
        lay.addLayout(steps)
        lay.addWidget(self.progress_bar)
        for w in (self._instruction, self._message_label, self._info, self._spread, self._mean, self._cross):
            lay.addWidget(w)
        lay.addWidget(self.plot)
        lay.addLayout(buttons)
        lay.addWidget(self._reminder)
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

    def reminder_text(self) -> str:
        return self._reminder.text()

    def progress_text(self) -> str:
        return self._progress_label.text()

    def spread_text(self) -> str:
        return self._spread.text()

    def mean_text(self) -> str:
        return self._mean.text()

    def cross_text(self) -> str:
        return self._cross.text()

    def order_text(self) -> str:
        return self._order.text()

    @property
    def step(self) -> int:
        """The calibration step shown: 1 relief, 2 action, 3 pickups, 4 intonation."""
        return self._step

    def chip_state(self, number: int) -> str:
        """"pending", "ok", "sharp", "flat" or "unsure": the last result of the string against the tolerance."""
        result = self.session.results.get(number)
        return "pending" if result is None else result.verdict(self.session.tolerance).value

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
        self.pickups.cancel()
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
        self.pickups.set_audio_enabled(has_input)
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
        if self._step == 4 and self.assistant_box.isEnabled():
            self._on_event(self.session.feed(reading))
        elif self._step == 3:
            self.pickups.feed(reading)
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
        if event in (Event.NOT_THE_OCTAVE, Event.NOT_THE_OPEN_STRING):
            self._message = S.intonation_refusal(self.session.step.value, string)
        elif event is not None:
            self._message = ""
        elif self.session.progress > 0:
            self._message = ""  # a note that is being captured is the right one
        if event is not None or self._message != self._message_label.text():
            self._refresh()

    # ------------------------------------------------------------------ the calibration steps

    def go_to_step(self, number: int) -> None:
        """Show step 1..4 and remember it; leaving the pickups step stops its audio helpers."""
        if number == self._step:
            return
        if self._step == 3:
            self.pickups.cancel()
        self._step = number
        self.calibration.set_step(number)
        self._apply_step()

    def _apply_step(self) -> None:
        self.step_bar.set_step(self._step)
        for number, page in self._pages.items():
            page.setVisible(number == self._step)
        for number, drawing in self._drawings.items():
            drawing.setVisible(number == self._step)
        self.preset_row.setVisible(self._step != 4)
        self.bridge.setVisible(self._step == 4)
        # steps 1 to 3: the tuner on top and the drawing under it; step 4: the tuner centred
        self._tuner_column.setStretch(0, 1 if self._step == 4 else 0)
        self._tuner_column.setStretch(self._tuner_column.count() - 1, 1 if self._step == 4 else 0)

    def _on_preset_selected(self, name: str) -> None:
        self.calibration.select_preset(name)
        self._reload_panels()

    def _on_calibration_edited(self) -> None:
        self.preset_row.set_name(self.calibration.preset)
        self._reload_panels()

    def _reload_panels(self) -> None:
        for panel in (self.relief, self.action, self.pickups):
            panel.load()

    def _on_pickup_rounds(self, rounds: int) -> None:
        self.rounds_combo.setCurrentIndex(max(0, self.rounds_combo.findData(rounds)))

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

    def _on_repeat(self) -> None:
        self.session.repeat_last()
        self._message = ""
        self._refresh()

    def _on_rounds(self, index: int) -> None:
        self.session.set_rounds(int(self.rounds_combo.itemData(index)))
        self.store.save(rounds=self.session.rounds)
        self.pickups.set_rounds(self.session.rounds)
        self._message = ""
        self._refresh()

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
            kind = result.verdict(session.tolerance)
            return S.intonation_result(kind.value, session.string, result.offset,
                                       saddle_shift_mm(result.offset, self.scale_mm), result.stats.half_width)
        return S.intonation_instruction(session.step.value, session.string)

    def _refresh_stats(self) -> None:
        stats = self.session.current_stats()
        spread = stats is not None and stats.n >= 2
        self._spread.setText(S.intonation_spread(stats.sd_open, stats.sd_harmonic, stats.sd_fretted) if spread else "")
        interval = stats is not None and stats.half_width is not None
        self._mean.setText(S.intonation_mean(stats.mean, stats.half_width, stats.n) if interval else "")
        warn = stats is not None and stats.cross_warning
        self._cross.setText(S.intonation_cross(stats.mean_cross) if warn else "")
        for label in (self._spread, self._mean, self._cross):
            label.setVisible(bool(label.text()))
        self.plot.set_stats(stats, self.session.tolerance)

    def _refresh(self) -> None:
        """Everything the session state decides: chips, progress, texts, statistics and the bridge."""
        session = self.session
        self._progress_label.setText("" if session.step is None else S.intonation_progress(
            session.round, session.rounds, session.step.value))
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
        detune = session.open_detune
        detuned = detune is not None and abs(detune) > DETUNED_CENTS
        self._info.setText(S.intonation_detuned(detune) if detuned else "")
        self._info.setVisible(detuned)
        self._refresh_stats()
        self.repeat_button.setEnabled(session.can_repeat)
        self.progress_bar.setValue(round(session.progress * 100))
        self.bridge.set_results({n: (r.offset, r.verdict(session.tolerance)) for n, r in session.results.items()},
                                session.string)
