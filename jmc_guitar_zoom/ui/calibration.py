"""The steps of «Calibración» around the intonation assistant: relief, action and pickups, with their drawings.

Everything here is measured by the user (a feeler gauge or a ruler) and typed in; the logic that turns a measure
into advice lives in ``jmc_guitar_zoom.calibration`` (no Qt). The panels write the Spanish text and paint the
drawings; the pickups panel also reads the audio readings the screen hands it (guided plucks for the level of each
string, and a sustained note for the magnetic pull).
"""

from __future__ import annotations

import dataclasses
import math

from PySide6.QtCore import QLocale, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from jmc_guitar_zoom.audio.pitch import PitchReading
from jmc_guitar_zoom.calibration import (BRIDGE_SADDLES, BRIDGE_TWO_POSTS, PRESETS, ActionMove, BalanceResult, PickupMove, PluckLevels, ReliefMove,
                                         action_advice, balance, magnetic_pull, pickup_advice, position_balance,
                                         relief_advice, saddle_arc, two_post_advice)

from . import strings as S
from . import tokens
from .fonts import ui_font
from .settings import POST_SPACING_RANGE, STEPS, CalibrationStore

STRINGS = (6, 5, 4, 3, 2, 1)
ROUNDS = S.INTONATION_ROUNDS_RANGE
PULL_SECONDS = 3.5  # a sustained note is judged after this long at the latest
PULL_GAP_SECONDS = 0.25  # no pitch for this long ends the note


def _spin(low: float, high: float, step: float, decimals: int, suffix: str, name: str,
          special: str | None = None) -> QDoubleSpinBox:
    """A spin box that writes numbers with a decimal comma; ``special`` is what its minimum (no measure) shows."""
    spin = QDoubleSpinBox()
    spin.setLocale(QLocale(QLocale.Language.Spanish, QLocale.Country.Spain))
    spin.setRange(low, high)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setAccessibleName(name)
    spin.setKeyboardTracking(False)
    if special is not None:
        spin.setSpecialValueText(special)
    spin.setMinimumWidth(QFontMetrics(spin.font()).horizontalAdvance(spin.textFromValue(high) + suffix) + 74)
    return spin


def _label(role: str = "reason", text: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(wrap)
    label.setProperty("role", role)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


def _caption(text: str) -> QLabel:
    return _label("reason", text, wrap=False)


def _arrow(p: QPainter, x: float, y: float, up: bool, length: float, color) -> None:
    """A vertical arrow starting at (x, y) and pointing up or down."""
    sign = -1 if up else 1
    tip = y + sign * length
    p.setPen(QPen(color, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(color)
    p.drawLine(QPointF(x, y), QPointF(x, tip - sign * 4))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([QPointF(x, tip), QPointF(x - 8, tip - sign * 11), QPointF(x + 8, tip - sign * 11)]))


def _tick(p: QPainter, x: float, y: float, color) -> None:
    p.setPen(QPen(color, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(x - 9, y), QPointF(x - 3, y + 7), QPointF(x + 9, y - 8)]))


MOVE_TOKEN = {"ok": "status-ok", "raise": "status-warn", "lower": "status-danger"}


# ---------------------------------------------------------------------------------------------- the step bar


class StepBar(QWidget):
    """«1 Curvatura del mástil» … «4 Octavación»: free navigation, one checked button."""

    step_chosen = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setAccessibleName(S.CALIBRATION_STEPS_NAME)
        self.buttons: dict[int, QPushButton] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for number in range(STEPS[0], STEPS[1] + 1):
            button = QPushButton(f"{number} {S.CALIBRATION_STEP_NAMES[number - 1]}")
            button.setCheckable(True)
            button.setProperty("stepbar", True)
            group.addButton(button, number)
            lay.addWidget(button)
            self.buttons[number] = button
        lay.addStretch(1)
        group.idClicked.connect(self.step_chosen)  # a signal to a signal: no Python lambda holds the screen

    def set_step(self, number: int) -> None:
        self.buttons[number].setChecked(True)


class PresetRow(QWidget):
    """The guitar style the targets come from."""

    preset_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.combo = QComboBox()
        self.combo.setAccessibleName(S.CALIBRATION_PRESET)
        self.combo.setToolTip(S.CALIBRATION_PRESET_TIP)
        for preset in PRESETS:
            self.combo.addItem(preset.name, preset.name)
        self.combo.currentIndexChanged.connect(self._on_changed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(_caption(S.CALIBRATION_PRESET))
        lay.addWidget(self.combo)
        lay.addStretch(1)

    def set_name(self, name: str) -> None:
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(max(0, self.combo.findData(name)))
        self.combo.blockSignals(False)

    def _on_changed(self, index: int) -> None:
        self.preset_selected.emit(str(self.combo.itemData(index)))


# ---------------------------------------------------------------------------------------------- step 1: relief


class NeckView(QWidget):
    """The neck seen from the side with its bow exaggerated: the measured one solid, the target one dashed.

    A straight line is the string; the fretboard dips under it by the relief. The truss-rod nut sits at the
    headstock end with a curved arrow for the turn (none when the relief is right).
    """

    PX_PER_MM = 70.0  # the bow is drawn this much larger than life
    MAX_BOW_PX = 90.0

    def __init__(self) -> None:
        super().__init__()
        self.bow_mm: float | None = None
        self.target_mm = 0.0
        self._move: ReliefMove | None = None
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(S.RELIEF_NECK_NAME)

    def set_state(self, measured_mm: float | None, target_mm: float, move: ReliefMove | None) -> None:
        self.bow_mm, self.target_mm, self._move = measured_mm, target_mm, move
        self.update()

    def turn(self) -> str | None:
        """"clockwise" (tighten), "counterclockwise" (loosen) or None when the relief is right or not measured."""
        return {ReliefMove.TIGHTEN: "clockwise", ReliefMove.LOOSEN: "counterclockwise"}.get(self._move)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        left, right = 90.0, w - 24.0
        string_y = h * 0.30
        # the nut of the truss rod and the headstock end
        p.setPen(QPen(tokens.color("border-strong"), 2))
        p.setBrush(tokens.color("surface-raised"))
        p.drawRoundedRect(QRectF(8, string_y - 6, left - 14, h * 0.62), 6, 6)
        p.setPen(tokens.color("text-secondary"))
        p.setFont(ui_font(12))
        p.drawText(QRectF(4, string_y + h * 0.62 + 2, left, 18), Qt.AlignmentFlag.AlignCenter, "alma")
        self._paint_nut(p, QPointF(left * 0.5 + 1, string_y + h * 0.30))
        # the string
        p.setPen(QPen(tokens.color("text-tertiary"), 2))
        p.drawLine(QPointF(left, string_y), QPointF(right, string_y))
        # the fretboard surface: target (dashed) and measured (solid)
        base = string_y + 4

        def curve(mm: float) -> QPainterPath:
            depth = min(self.MAX_BOW_PX, mm * self.PX_PER_MM)
            path = QPainterPath(QPointF(left, base))
            path.quadTo(QPointF((left + right) / 2, base + 2 * depth), QPointF(right, base))
            return path

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(tokens.color("status-ok"), 2.5, Qt.PenStyle.DashLine))
        p.drawPath(curve(self.target_mm))
        if self.bow_mm is not None:
            token = MOVE_TOKEN["ok"] if self._move is ReliefMove.OK else (
                "status-danger" if self._move is ReliefMove.TIGHTEN else "status-warn")
            p.setPen(QPen(tokens.color(token), 3.5))
            p.drawPath(curve(self.bow_mm))

    def _paint_nut(self, p: QPainter, centre: QPointF) -> None:
        p.setPen(QPen(tokens.color("text-secondary"), 2))
        p.setBrush(tokens.color("surface-sunken"))
        hexagon = QPolygonF([QPointF(centre.x() + 14 * math.cos(math.radians(60 * i)),
                                     centre.y() + 14 * math.sin(math.radians(60 * i))) for i in range(6)])
        p.drawPolygon(hexagon)
        turn = self.turn()
        if turn is None:
            return
        color = tokens.color("status-danger" if turn == "clockwise" else "status-warn")
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        radius = 26.0
        box = QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)
        # three quarters of a circle, from the top; Qt angles grow counter-clockwise (1/16 degree)
        start = 90 * 16
        span = (-250 if turn == "clockwise" else 250) * 16
        p.drawArc(box, start, span)
        end = math.radians(90 + (-250 if turn == "clockwise" else 250))
        tip = QPointF(centre.x() + radius * math.cos(end), centre.y() - radius * math.sin(end))
        heading = end + (-math.pi / 2 if turn == "clockwise" else math.pi / 2)  # the tangent of the arc at its end
        direction = QPointF(math.cos(heading), -math.sin(heading))
        normal = QPointF(-direction.y(), direction.x())
        head = QPolygonF([QPointF(tip.x() + direction.x() * 9, tip.y() + direction.y() * 9),
                          QPointF(tip.x() + normal.x() * 7, tip.y() + normal.y() * 7),
                          QPointF(tip.x() - normal.x() * 7, tip.y() - normal.y() * 7)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(head)


class ReliefPanel(QWidget):
    changed = Signal()

    def __init__(self, store: CalibrationStore) -> None:
        super().__init__()
        self.store = store
        self._method = _label("reason", S.RELIEF_METHOD)
        self.measured_spin = _spin(-0.01, 2.0, 0.01, 2, " mm", S.RELIEF_MEASURED, S.CALIBRATION_NOT_MEASURED)
        self.measured_spin.setValue(self.measured_spin.minimum())
        self.target_spin = _spin(0.0, 2.0, 0.01, 2, " mm", S.RELIEF_TARGET)
        self._advice = _label("instruction")
        self._safety = _label("notice", S.RELIEF_SAFETY)
        self.neck_view = NeckView()
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_caption(S.RELIEF_MEASURED))
        row.addWidget(self.measured_spin)
        row.addWidget(_caption(S.RELIEF_TARGET))
        row.addWidget(self.target_spin)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self._method)
        lay.addLayout(row)
        lay.addWidget(self._advice)
        lay.addWidget(self._safety)
        lay.addStretch(1)
        self.drawing = self.neck_view  # the screen shows it under the live tuner, so the page stays short
        self.load()
        self.measured_spin.valueChanged.connect(self._refresh)
        self.target_spin.valueChanged.connect(self._on_target)

    def method_text(self) -> str:
        return self._method.text()

    def safety_text(self) -> str:
        return self._safety.text()

    def advice_text(self) -> str:
        return self._advice.text()

    def measured_value(self) -> float | None:
        value = self.measured_spin.value()
        return None if value <= self.measured_spin.minimum() else round(value, 2)

    def load(self) -> None:
        """Show the values of the preset in use."""
        self.target_spin.blockSignals(True)
        self.target_spin.setValue(self.store.current().relief_mm)
        self.target_spin.blockSignals(False)
        self._refresh()

    def _on_target(self, value: float) -> None:
        self.store.edit(relief_mm=round(value, 2))
        self._refresh()
        self.changed.emit()

    def _refresh(self, *_args) -> None:
        measured, target = self.measured_value(), round(self.target_spin.value(), 2)
        if measured is None:
            self._advice.setText(S.RELIEF_ASK)
            self.neck_view.set_state(None, target, None)
            return
        advice = relief_advice(measured, target)
        self._advice.setText(S.relief_text(advice.move.value, advice.error_mm, measured, target))
        self.neck_view.set_state(measured, target, advice.move)


# ---------------------------------------------------------------------------------------------- step 2: action


class SaddleView(QWidget):
    """The six saddles seen from the front, raised by the fretboard-radius arc, with an arrow where one must move."""

    SADDLE_W = 46
    BASE = 26.0  # px of the lowest saddle
    PX_PER_MM = 14.0

    def __init__(self) -> None:
        super().__init__()
        self._profile = {n: 0.0 for n in STRINGS}
        self._moves: dict[int, ActionMove] = {}
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(S.ACTION_SADDLES_NAME)

    def set_state(self, profile: dict[int, float], moves: dict[int, ActionMove]) -> None:
        self._profile, self._moves = dict(profile), dict(moves)
        self.update()

    def profile(self, number: int) -> float:
        """Height of the saddle above those of strings 6 and 1, in mm, for the radius shown."""
        return self._profile[number]

    def arrow(self, number: int) -> str | None:
        """"raise", "lower", "ok" or None for a string not measured."""
        move = self._moves.get(number)
        return None if move is None else move.value

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = min(self.width() - 24, 620)
        left = (self.width() - width) / 2
        slot = width / len(STRINGS)
        floor = self.height() - 30
        p.setPen(QPen(tokens.color("border-control"), 1.5))
        p.drawLine(QPointF(left, floor), QPointF(left + width, floor))
        for i, number in enumerate(STRINGS):
            cx = left + slot * (i + 0.5)
            height = self.BASE + self._profile[number] * self.PX_PER_MM
            top = floor - height
            p.setPen(QPen(tokens.color("border-strong"), 1.5))
            p.setBrush(tokens.color("surface-control"))
            p.drawRoundedRect(QRectF(cx - self.SADDLE_W / 2, top, self.SADDLE_W, height), 5, 5)
            p.setPen(QPen(tokens.color("text-tertiary"), 1.5))
            p.drawLine(QPointF(cx, top - 14), QPointF(cx, top))
            p.setPen(tokens.color("text-secondary"))
            p.setFont(ui_font(13))
            p.drawText(QRectF(cx - 40, floor + 4, 80, 20), Qt.AlignmentFlag.AlignCenter, S.string_chip(number))
            move = self._moves.get(number)
            if move is None:
                continue
            color = tokens.color(MOVE_TOKEN[move.value])
            if move is ActionMove.OK:
                _tick(p, cx, top - 28, color)
            else:
                up = move is ActionMove.RAISE
                _arrow(p, cx, top - 6 if up else top - 52, up, 34, color)


class PostView(QWidget):
    """A two-post bridge seen from the side: the bass post to the left, the treble post to the right, an arrow on each."""

    POST_W = 34
    POST_H = 70

    def __init__(self) -> None:
        super().__init__()
        self._moves: dict[str, ActionMove] = {}
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(S.ACTION_POSTS_NAME)

    def set_state(self, moves: dict[str, ActionMove]) -> None:
        self._moves = dict(moves)
        self.update()

    def arrow(self, side: str) -> str | None:
        """"raise", "lower", "ok" or None when there is no advice yet; ``side`` is "bass" or "treble"."""
        move = self._moves.get(side)
        return None if move is None else move.value

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = min(self.width() - 24, 420)
        left = (self.width() - width) / 2
        floor = self.height() - 30
        base_top = floor - 16
        p.setPen(QPen(tokens.color("border-strong"), 1.5))
        p.setBrush(tokens.color("surface-control"))
        p.drawRoundedRect(QRectF(left, base_top, width, 16), 4, 4)  # the body under the bridge
        top = base_top - self.POST_H
        centres = {"bass": left + width * 0.2, "treble": left + width * 0.8}
        p.drawRoundedRect(QRectF(left + width * 0.2, top - 14, width * 0.6, 14), 5, 5)  # the bridge bar on the posts
        for side, cx in centres.items():
            p.setPen(QPen(tokens.color("border-strong"), 1.5))
            p.setBrush(tokens.color("surface-control"))
            p.drawRoundedRect(QRectF(cx - self.POST_W / 2, top, self.POST_W, self.POST_H + 2), 5, 5)
            p.setPen(tokens.color("text-secondary"))
            p.setFont(ui_font(13))
            p.drawText(QRectF(cx - 60, floor + 4, 120, 20), Qt.AlignmentFlag.AlignCenter, S.ACTION_POSTS_SIDES[side])
            move = self._moves.get(side)
            if move is None:
                continue
            color = tokens.color(MOVE_TOKEN[move.value])
            if move is ActionMove.OK:
                _tick(p, cx, top - 36, color)
            else:
                up = move is ActionMove.RAISE
                _arrow(p, cx, top - 20 if up else top - 66, up, 34, color)


class ActionPanel(QWidget):
    changed = Signal()

    def __init__(self, store: CalibrationStore) -> None:
        super().__init__()
        self.store = store
        self._method = _label("reason", S.ACTION_METHOD)
        self._rule = _label("hint", S.ACTION_RULE)
        self.spins: dict[int, QDoubleSpinBox] = {}
        self._advice: dict[int, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        for column, number in enumerate(STRINGS):
            spin = _spin(0.0, 10.0, 0.05, 2, " mm", S.string_chip_name(number, None), S.CALIBRATION_NOT_MEASURED)
            self.spins[number] = spin
            advice = _label("reason")
            advice.setAlignment(Qt.AlignmentFlag.AlignTop)
            advice.setMinimumWidth(96)
            self._advice[number] = advice
            grid.addWidget(_caption(S.string_chip(number)), 0, column)
            grid.addWidget(spin, 1, column)
            grid.addWidget(advice, 2, column)
            grid.setColumnStretch(column, 1)
            spin.valueChanged.connect(self._refresh)
        self.bass_target_spin = _spin(0.1, 10.0, 0.05, 2, " mm", S.CALIBRATION_BASS + " " + S.CALIBRATION_TARGET.lower())
        self.treble_target_spin = _spin(0.1, 10.0, 0.05, 2, " mm",
                                        S.CALIBRATION_TREBLE + " " + S.CALIBRATION_TARGET.lower())
        self.radius_spin = _spin(5.0, 30.0, 0.25, 2, '"', S.ACTION_RADIUS)
        targets = QHBoxLayout()
        targets.setSpacing(10)
        for caption, spin in ((f"{S.CALIBRATION_TARGET} 6", self.bass_target_spin),
                              (f"{S.CALIBRATION_TARGET} 1", self.treble_target_spin),
                              (S.ACTION_RADIUS, self.radius_spin)):
            targets.addWidget(_caption(caption))
            targets.addWidget(spin)
        targets.addStretch(1)
        self.bridge_combo = QComboBox()
        self.bridge_combo.setAccessibleName(S.ACTION_BRIDGE)
        self.bridge_combo.addItem(S.ACTION_BRIDGE_SADDLES, BRIDGE_SADDLES)
        self.bridge_combo.addItem(S.ACTION_BRIDGE_POSTS, BRIDGE_TWO_POSTS)
        self.post_spacing_spin = _spin(POST_SPACING_RANGE[0], POST_SPACING_RANGE[1], 0.5, 1, " mm",
                                       S.ACTION_POST_SPACING)
        self.post_spacing_spin.setToolTip(S.ACTION_POST_SPACING_TIP)
        self._post_caption = _caption(S.ACTION_POST_SPACING)
        bridge_row = QHBoxLayout()
        bridge_row.setSpacing(10)
        bridge_row.addWidget(_caption(S.ACTION_BRIDGE))
        bridge_row.addWidget(self.bridge_combo)
        bridge_row.addWidget(self._post_caption)
        bridge_row.addWidget(self.post_spacing_spin)
        bridge_row.addStretch(1)
        self.saddles = SaddleView()
        self.posts = PostView()
        self._arc = _label("instruction")
        self._posts_rule = _label("hint", S.ACTION_POSTS_RULE)
        self._post_labels = {side: _label("instruction") for side in ("bass", "treble")}
        self._remeasure = _label("hint")
        self._middle = _label("reason")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self._method)
        lay.addLayout(bridge_row)
        lay.addLayout(targets)
        lay.addLayout(grid)
        lay.addWidget(self._rule)
        lay.addWidget(self._arc)
        lay.addWidget(self._posts_rule)
        for label in (*self._post_labels.values(), self._remeasure, self._middle):
            lay.addWidget(label)
        lay.addStretch(1)
        self.drawing = QWidget()  # both views live here; the screen shows it under the live tuner
        drawing = QVBoxLayout(self.drawing)
        drawing.setContentsMargins(0, 0, 0, 0)
        drawing.addWidget(self.saddles)
        drawing.addWidget(self.posts)
        self.load()
        for spin in (self.bass_target_spin, self.treble_target_spin, self.radius_spin):
            spin.valueChanged.connect(self._on_target)
        self.post_spacing_spin.valueChanged.connect(self._on_spacing)
        self.bridge_combo.currentIndexChanged.connect(self._on_bridge)

    def method_text(self) -> str:
        return self._method.text()

    def rule_text(self) -> str:
        return self._rule.text()

    def advice_text(self, number: int) -> str:
        return self._advice[number].text()

    def arc_text(self) -> str:
        return self._arc.text()

    def post_text(self, side: str) -> str:
        return self._post_labels[side].text()

    def remeasure_text(self) -> str:
        return self._remeasure.text()

    def middle_text(self) -> str:
        return self._middle.text()

    def arc_label_visible(self) -> bool:
        return self._arc.isVisibleTo(self)

    def load(self) -> None:
        preset = self.store.current()
        for spin, value in ((self.bass_target_spin, preset.action_bass_mm),
                            (self.treble_target_spin, preset.action_treble_mm), (self.radius_spin, preset.radius_in),
                            (self.post_spacing_spin, preset.post_spacing_mm)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.bridge_combo.blockSignals(True)
        self.bridge_combo.setCurrentIndex(max(0, self.bridge_combo.findData(preset.bridge_type)))
        self.bridge_combo.blockSignals(False)
        self._refresh()

    def _on_bridge(self, _index: int) -> None:
        bridge = self.bridge_combo.currentData()
        if bridge != self.store.current().bridge_type:  # choosing what the preset already has changes nothing
            self.store.edit(bridge_type=bridge)
            self.changed.emit()
        self._refresh()

    def _on_spacing(self, _value: float) -> None:
        self.store.edit(post_spacing_mm=round(self.post_spacing_spin.value(), 1))
        self._refresh()
        self.changed.emit()

    def _on_target(self, _value: float) -> None:
        self.store.edit(action_bass_mm=round(self.bass_target_spin.value(), 2),
                        action_treble_mm=round(self.treble_target_spin.value(), 2),
                        radius_in=round(self.radius_spin.value(), 2))
        self._refresh()
        self.changed.emit()

    def _refresh(self, *_args) -> None:
        preset = self.store.current()
        posts = preset.bridge_type == BRIDGE_TWO_POSTS
        for widget in (self.saddles, self._rule, self._arc):
            widget.setVisible(not posts)
        for widget in (self.posts, self.post_spacing_spin, self._post_caption, self._posts_rule, self._remeasure,
                       *self._post_labels.values()):
            widget.setVisible(posts)
        measured = {n: round(s.value(), 2) for n, s in self.spins.items() if s.value() > s.minimum()}
        if posts:
            for label in self._advice.values():
                label.setText("")
            self._refresh_posts(preset, measured)
            return
        self._middle.setText("")
        self._middle.setVisible(False)
        advice = action_advice(measured, preset)
        for number, label in self._advice.items():
            item = advice.get(number)
            label.setText("" if item is None else S.action_text(item.move.value, item.error_mm, item.target_mm,
                                                                 item.saddle_mm))
        arc = saddle_arc(preset.radius_in, preset.bridge_span_mm)
        self._arc.setText(S.arc_text(preset.radius_in, arc[4], arc[5]))
        self.saddles.set_state(arc, {n: a.move for n, a in advice.items()})

    def _refresh_posts(self, preset, measured: dict[int, float]) -> None:
        if 6 not in measured or 1 not in measured:
            for label in (*self._post_labels.values(), self._remeasure, self._middle):
                label.setText("")
            self._middle.setVisible(False)
            self.posts.set_state({})
            return
        middle = {n: v for n, v in measured.items() if n not in (6, 1)}
        advice = two_post_advice(measured[6], measured[1], preset, middle=middle)
        self._post_labels["bass"].setText(S.post_text("bass", advice.bass_move.value, advice.bass_post_mm))
        self._post_labels["treble"].setText(S.post_text("treble", advice.treble_move.value, advice.treble_post_mm))
        self._remeasure.setText(S.ACTION_POSTS_REMEASURE)
        self._middle.setText(S.post_middle_text(advice.middle_mismatch_mm) if advice.middle_mismatch_mm else "")
        self._middle.setVisible(bool(advice.middle_mismatch_mm))
        self.posts.set_state({"bass": advice.bass_move, "treble": advice.treble_move})


# ---------------------------------------------------------------------------------------------- step 3: pickups


class PickupView(QWidget):
    """A pickup seen from the front: bass side to the left, treble to the right, an arrow on each end."""

    def __init__(self) -> None:
        super().__init__()
        self._moves: dict[str, PickupMove] = {}
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(S.PICKUP_VIEW_NAME)

    def set_moves(self, moves: dict[str, PickupMove]) -> None:
        self._moves = dict(moves)
        self.update()

    def arrow(self, side: str) -> str | None:
        """"raise", "lower", "ok" or None for a side not measured."""
        move = self._moves.get(side)
        return None if move is None else move.value

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = min(self.width() - 40, 560)
        left = (self.width() - width) / 2
        mid = self.height() * 0.62
        body = QRectF(left, mid - 16, width, 32)
        p.setPen(QPen(tokens.color("border-strong"), 2))
        p.setBrush(tokens.color("surface-raised"))
        p.drawRoundedRect(body, 10, 10)
        p.setBrush(tokens.color("text-tertiary"))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(6):
            p.drawEllipse(QPointF(left + width * (i + 0.5) / 6, mid), 4.5, 4.5)
        p.setPen(tokens.color("text-secondary"))
        p.setFont(ui_font(13, QFont.Weight.Medium))
        p.drawText(QRectF(left, mid + 20, 140, 20), Qt.AlignmentFlag.AlignLeft, S.CALIBRATION_BASS)
        p.drawText(QRectF(left + width - 140, mid + 20, 140, 20), Qt.AlignmentFlag.AlignRight, S.CALIBRATION_TREBLE)
        for side, x in (("bass", left + 22), ("treble", left + width - 22)):
            move = self._moves.get(side)
            if move is None:
                continue
            color = tokens.color(MOVE_TOKEN[move.value])
            if move is PickupMove.OK:
                _tick(p, x, mid - 34, color)
            else:
                up = move is PickupMove.RAISE
                _arrow(p, x, mid - 20 if up else mid - 66, up, 38, color)


class LevelsChart(QWidget):
    """A bar per string for its level against the mean of the six, with a whisker of one standard deviation."""

    RANGE_DB = 6.0  # the bars span ±6 dB at least

    def __init__(self) -> None:
        super().__init__()
        self._values: dict[int, tuple[float, float | None]] = {}
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setAccessibleName(S.PICKUP_CHART_NAME)

    def set_result(self, result: BalanceResult | None) -> None:
        self._values = {} if result is None else {n: (s.relative_db, s.sd_db) for n, s in result.strings.items()}
        self.update()

    def values(self) -> dict[int, tuple[float, float | None]]:
        """string -> (level against the mean in dB, the standard deviation or None with one round)."""
        return dict(self._values)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top, bottom = 8.0, self.height() - 26.0
        reach = max([self.RANGE_DB] + [abs(v) + (sd or 0.0) for v, sd in self._values.values()])
        zero = (top + bottom) / 2
        scale = (bottom - top) / 2 / reach
        width = min(self.width() - 24, 560)
        left = (self.width() - width) / 2
        slot = width / len(STRINGS)
        p.setPen(QPen(tokens.color("tuner-baseline"), 1))
        p.drawLine(QPointF(left, zero), QPointF(left + width, zero))
        p.setPen(tokens.color("text-secondary"))
        p.setFont(ui_font(12))
        for i, number in enumerate(STRINGS):
            cx = left + slot * (i + 0.5)
            p.drawText(QRectF(cx - 40, bottom + 4, 80, 18), Qt.AlignmentFlag.AlignCenter, S.string_chip(number))
            value = self._values.get(number)
            if value is None:
                continue
            level, sd = value
            color = tokens.color("accent")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            y = zero - level * scale
            p.drawRoundedRect(QRectF(cx - 16, min(y, zero), 32, max(2.0, abs(zero - y))), 3, 3)
            if sd is not None:
                p.setPen(QPen(tokens.color("text-primary"), 2))
                p.drawLine(QPointF(cx, y - sd * scale), QPointF(cx, y + sd * scale))
                for edge in (y - sd * scale, y + sd * scale):
                    p.drawLine(QPointF(cx - 5, edge), QPointF(cx + 5, edge))


class PickupsPanel(QWidget):
    changed = Signal()
    rounds_changed = Signal(int)

    def __init__(self, store: CalibrationStore, rounds: int) -> None:
        super().__init__()
        self.store = store
        self.rounds = rounds
        self.levels = PluckLevels()
        self._mode: str | None = None  # "balance", "pull" or None
        self._round, self._index = 1, 0
        self._means: dict[str, float] = {}
        self._pull: list[PitchReading] = []
        self._pull_voiced = 0.0
        self._method = _label("reason", S.PICKUP_METHOD)
        self.position_combo = QComboBox()
        self.position_combo.setAccessibleName(S.PICKUP_POSITION)
        self.bass_spin = _spin(0.0, 10.0, 0.1, 1, " mm", S.CALIBRATION_BASS, S.CALIBRATION_NOT_MEASURED)
        self.treble_spin = _spin(0.0, 10.0, 0.1, 1, " mm", S.CALIBRATION_TREBLE, S.CALIBRATION_NOT_MEASURED)
        self.bass_target_spin = _spin(0.0, 10.0, 0.1, 1, " mm", S.CALIBRATION_BASS + " " + S.CALIBRATION_TARGET.lower())
        self.treble_target_spin = _spin(0.0, 10.0, 0.1, 1, " mm",
                                        S.CALIBRATION_TREBLE + " " + S.CALIBRATION_TARGET.lower())
        self._bass_advice = _label("reason")
        self._treble_advice = _label("reason")
        self.view = PickupView()
        self._hint = _label("hint", S.PICKUP_AUDIO_HINT)
        self.balance_button = QPushButton(S.PICKUP_BALANCE)
        self.magnet_button = QPushButton(S.PICKUP_MAGNET)
        self.rounds_combo = QComboBox()
        self.rounds_combo.setAccessibleName(S.CALIBRATION_ROUNDS)
        for n in range(ROUNDS[0], ROUNDS[1] + 1):
            self.rounds_combo.addItem(str(n), n)
        self.rounds_combo.setCurrentIndex(max(0, self.rounds_combo.findData(rounds)))
        self._instruction = _label("instruction")
        self._message = _label("notice")
        self.chart = LevelsChart()
        self._balance = _label("instruction")
        self._positions = _label("reason")
        self._magnetic = _label("instruction")

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_caption(S.PICKUP_POSITION))
        top.addWidget(self.position_combo)
        top.addWidget(_caption(f"{S.CALIBRATION_TARGET} {S.CALIBRATION_BASS.lower()}"))
        top.addWidget(self.bass_target_spin)
        top.addWidget(_caption(f"{S.CALIBRATION_TARGET} {S.CALIBRATION_TREBLE.lower()}"))
        top.addWidget(self.treble_target_spin)
        top.addStretch(1)
        measures = QHBoxLayout()
        measures.setSpacing(10)
        measures.addWidget(_caption(f"{S.CALIBRATION_MEASURED} {S.CALIBRATION_BASS.lower()}"))
        measures.addWidget(self.bass_spin)
        measures.addWidget(_caption(f"{S.CALIBRATION_MEASURED} {S.CALIBRATION_TREBLE.lower()}"))
        measures.addWidget(self.treble_spin)
        measures.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.balance_button)
        buttons.addWidget(_caption(S.CALIBRATION_ROUNDS))
        buttons.addWidget(self.rounds_combo)
        buttons.addWidget(self.magnet_button)
        buttons.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._method)
        lay.addLayout(top)
        lay.addLayout(measures)
        lay.addWidget(self._bass_advice)
        lay.addWidget(self._treble_advice)
        lay.addWidget(self._hint)
        lay.addLayout(buttons)
        for widget in (self._instruction, self._message, self._balance, self._positions, self._magnetic):
            lay.addWidget(widget)
        lay.addStretch(1)
        self.drawing = QWidget()  # the pickup and the levels chart, shown by the screen under the live tuner
        drawing = QVBoxLayout(self.drawing)
        drawing.setContentsMargins(0, 0, 0, 0)
        drawing.setSpacing(6)
        drawing.addWidget(self.view, stretch=1)
        drawing.addWidget(self.chart)
        self.load()
        self.position_combo.currentIndexChanged.connect(self._on_position)
        self.bass_spin.valueChanged.connect(self._refresh)
        self.treble_spin.valueChanged.connect(self._refresh)
        self.bass_target_spin.valueChanged.connect(self._on_target)
        self.treble_target_spin.valueChanged.connect(self._on_target)
        self.balance_button.clicked.connect(self._on_balance_button)
        self.magnet_button.clicked.connect(self._on_magnet_button)
        self.rounds_combo.currentIndexChanged.connect(self._on_rounds)

    # -- read-only views

    def advice_text(self, side: str) -> str:
        return (self._bass_advice if side == "bass" else self._treble_advice).text()

    def instruction_text(self) -> str:
        return self._instruction.text()

    def message_text(self) -> str:
        return self._message.text()

    def balance_text(self) -> str:
        return self._balance.text()

    def positions_text(self) -> str:
        return self._positions.text()

    def magnetic_text(self) -> str:
        return self._magnetic.text()

    def position(self) -> str:
        return str(self.position_combo.currentData())

    # -- the preset

    def load(self) -> None:
        """Show the positions and targets of the preset in use (the chosen position is kept when it still exists)."""
        preset = self.store.current()
        keep = self.position_combo.currentData()
        self.position_combo.blockSignals(True)
        self.position_combo.clear()
        for name, _kind in preset.pickups:
            self.position_combo.addItem(S.PICKUP_POSITIONS[name], name)
        self.position_combo.setCurrentIndex(max(0, self.position_combo.findData(keep)))
        self.position_combo.blockSignals(False)
        target = preset.target_for(self.position())
        for spin, value in ((self.bass_target_spin, target.bass_mm), (self.treble_target_spin, target.treble_mm)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._refresh()

    def _on_position(self, _index: int) -> None:
        self.load()

    def _on_target(self, _value: float) -> None:
        preset = self.store.current()
        kind = preset.pickup_type(self.position())
        targets = tuple(dataclasses.replace(t, bass_mm=round(self.bass_target_spin.value(), 1),
                                            treble_mm=round(self.treble_target_spin.value(), 1))
                        if t.pickup_type == kind else t for t in preset.pickup_targets)
        self.store.edit(pickup_targets=targets)
        self._refresh()
        self.changed.emit()

    # -- measures typed in

    def _refresh(self, *_args) -> None:
        bass = self.bass_spin.value() if self.bass_spin.value() > self.bass_spin.minimum() else None
        treble = self.treble_spin.value() if self.treble_spin.value() > self.treble_spin.minimum() else None
        target = self.store.current().target_for(self.position())
        advice = pickup_advice(self.position(), target.bass_mm if bass is None else round(bass, 1),
                               target.treble_mm if treble is None else round(treble, 1), self.store.current())
        moves = {}
        for side, value, label in (("bass", bass, self._bass_advice), ("treble", treble, self._treble_advice)):
            item = advice[side]
            if value is None:
                label.setText("")
                continue
            moves[side] = item.move
            label.setText(S.pickup_text(item.move.value, side, item.string, item.measured_mm, item.target_mm))
        self.view.set_moves(moves)

    # -- audio help

    def set_rounds(self, rounds: int) -> None:
        """The rounds chosen elsewhere (the intonation assistant keeps the same setting)."""
        self.rounds = rounds
        self.rounds_combo.blockSignals(True)
        self.rounds_combo.setCurrentIndex(max(0, self.rounds_combo.findData(rounds)))
        self.rounds_combo.blockSignals(False)

    def _on_rounds(self, index: int) -> None:
        self.rounds = int(self.rounds_combo.itemData(index))
        self.rounds_changed.emit(self.rounds)

    def set_audio_enabled(self, enabled: bool) -> None:
        self.balance_button.setEnabled(enabled)
        self.magnet_button.setEnabled(enabled)
        if not enabled:
            self.cancel()

    def cancel(self) -> None:
        """Stop a balance run or a magnetic-pull check in progress."""
        self._mode = None
        self._pull = []
        self._instruction.setText("")
        self._message.setText("")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.balance_button.setText(S.PICKUP_STOP if self._mode == "balance" else S.PICKUP_BALANCE)
        self.magnet_button.setText(S.PICKUP_STOP if self._mode == "pull" else S.PICKUP_MAGNET)
        for label in (self._instruction, self._message, self._balance, self._positions, self._magnetic):
            label.setVisible(bool(label.text()))

    def _on_balance_button(self) -> None:
        if self._mode == "balance":
            self.cancel()
            return
        self.cancel()
        self._mode = "balance"
        self.levels = PluckLevels()
        self._round, self._index = 1, 0
        self._balance.setText("")
        self._positions.setText("")
        self._magnetic.setText("")
        self.chart.set_result(None)
        self._show_balance_round()

    def _on_magnet_button(self) -> None:
        if self._mode == "pull":
            self.cancel()
            return
        self.cancel()
        self._mode = "pull"
        self._pull, self._pull_voiced = [], 0.0
        self._magnetic.setText("")
        self._instruction.setText(S.PICKUP_PULL_ASK)
        self._sync_buttons()

    def _show_balance_round(self) -> None:
        self._instruction.setText(S.balance_round_text(self._round, self.rounds, STRINGS[self._index]))
        self._sync_buttons()

    def feed(self, reading: PitchReading) -> None:
        """Every reading of the input while this step is shown."""
        if self._mode == "balance":
            self._feed_balance(reading)
        elif self._mode == "pull":
            self._feed_pull(reading)

    def _feed_balance(self, reading: PitchReading) -> None:
        string = STRINGS[self._index]
        refusal = self.levels.add(reading, string)
        if refusal is not None:
            self._message.setText(S.balance_refusal(refusal.string))
            self._sync_buttons()
            return
        if len(self.levels.levels.get(string, ())) < self._round:
            return
        self._message.setText("")
        self._index += 1
        if self._index == len(STRINGS):
            self._index, self._round = 0, self._round + 1
        if self._round > self.rounds:
            self._finish_balance()
        else:
            self._show_balance_round()

    def _finish_balance(self) -> None:
        self._mode = None
        self._instruction.setText("")
        result = balance(self.levels.levels)
        self.chart.set_result(result)
        self._balance.setText(S.balance_summary(result.advice.value if result.advice else "",
                                                result.bass_minus_treble_db))
        self._means[self.position()] = result.mean_db
        names = {name for name, _kind in self.store.current().pickups}
        measured = {p: v for p, v in self._means.items() if p in names}
        if len(measured) >= 2:
            compared = position_balance(measured)
            self._positions.setText(S.position_summary(compared.relative_db, compared.flagged))
        else:
            self._positions.setText("")
        self._sync_buttons()

    def _feed_pull(self, reading: PitchReading) -> None:
        if reading.frequency is not None and reading.cents is not None:
            self._pull.append(reading)
            self._pull_voiced = reading.time
            if reading.time - self._pull[0].time >= PULL_SECONDS:
                self._finish_pull()
        elif self._pull and reading.time - self._pull_voiced >= PULL_GAP_SECONDS:
            self._finish_pull()

    def _finish_pull(self) -> None:
        result = magnetic_pull(self._pull)
        self._pull = []
        if not result.enough_data:
            self._message.setText(S.PICKUP_PULL_SHORT)
            self._sync_buttons()
            return
        self._mode = None
        self._instruction.setText("")
        self._message.setText("")
        self._magnetic.setText(S.pull_warning(result.peak_to_peak_cents) if result.warn else S.PICKUP_PULL_CLEAN)
        self._sync_buttons()
