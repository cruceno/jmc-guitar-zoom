"""String action at the 12th fret and the saddle-height arc of a fretboard radius."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .presets import GuitarPreset

MAX_ACTION_MM = 10.0
STRINGS = (6, 5, 4, 3, 2, 1)
SADDLE_RATIO = 2.0  # the 12th fret is half the scale: a saddle change of d moves the string there by about d/2


class ActionMove(Enum):
    OK = "ok"
    RAISE = "raise"  # the action is too low
    LOWER = "lower"  # the action is too high


@dataclass(frozen=True)
class ActionAdvice:
    string: int
    target_mm: float
    error_mm: float  # measured - target; positive means too high
    move: ActionMove
    saddle_mm: float  # how much to move that string's saddle (magnitude, in the direction of ``move``); 0 when OK


def action_targets(preset: GuitarPreset) -> dict[int, float]:
    """Target action per string, linear between string 6 (bass) and string 1 (treble)."""
    return {s: preset.action_bass_mm + (preset.action_treble_mm - preset.action_bass_mm) * (6 - s) / 5
            for s in STRINGS}


def action_advice(measured: Mapping[int, float], preset: GuitarPreset,
                  tolerance_mm: float = 0.1) -> dict[int, ActionAdvice]:
    """Advice for each measured string (12th fret, mm); unmeasured strings are absent from the result."""
    targets = action_targets(preset)
    result: dict[int, ActionAdvice] = {}
    for string, value in measured.items():
        if string not in targets:
            raise ValueError(f"strings are numbered 1 to 6, got {string}")
        value = float(value)
        if not math.isfinite(value) or value <= 0 or value > MAX_ACTION_MM:
            raise ValueError(f"the action must be between 0 and {MAX_ACTION_MM} mm, got {value}")
        error = round(value - targets[string], 6)
        if abs(error) <= tolerance_mm:
            move, saddle = ActionMove.OK, 0.0
        else:
            move = ActionMove.LOWER if error > 0 else ActionMove.RAISE
            saddle = abs(error) * SADDLE_RATIO
        result[string] = ActionAdvice(string, targets[string], error, move, saddle)
    return result


def saddle_arc(radius_in: float, span_mm: float) -> dict[int, float]:
    """Saddle height of each string above strings 6 and 1 (mm), for a fretboard of ``radius_in`` inches.

    The six strings sit evenly spaced across ``span_mm``; the height of each is the sagitta of the arc
    ``R - sqrt(R^2 - x^2)`` at the outer strings minus the one at its own position, so strings 6 and 1 are 0.
    """
    if radius_in <= 0 or span_mm <= 0:
        raise ValueError("the radius and the span must be positive")
    radius = radius_in * 25.4

    def drop(x: float) -> float:
        return radius - math.sqrt(radius * radius - x * x)

    half = span_mm / 2
    step = span_mm / 5
    outer = drop(half)
    return {s: outer - drop(-half + i * step) for i, s in enumerate(STRINGS)}


@dataclass(frozen=True)
class TwoPostAdvice:
    """Per-post advice for a bridge whose height is set only at two posts (Tune-o-matic, Ibanez Gibraltar)."""

    bass_move: ActionMove
    bass_post_mm: float  # magnitude of the post move, in the direction of ``bass_move``; 0 when OK
    treble_move: ActionMove
    treble_post_mm: float
    expected_mm: dict[int, float]  # action of strings 6..1 after the move, if the bridge radius matches the fretboard
    middle_mismatch_mm: dict[int, float]  # measured middle string - expectation (information only)


def _validated(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0 or value > MAX_ACTION_MM:
        raise ValueError(f"the action must be between 0 and {MAX_ACTION_MM} mm, got {value}")
    return value


def _post_move(move_mm: float, tolerance_mm: float) -> tuple[ActionMove, float]:
    if abs(move_mm) <= 2 * tolerance_mm + 1e-9:
        return ActionMove.OK, 0.0
    return (ActionMove.LOWER if move_mm < 0 else ActionMove.RAISE), abs(move_mm)


def two_post_advice(measured_6: float, measured_1: float, preset: GuitarPreset, tolerance_mm: float = 0.1,
                    middle: Mapping[int, float] | None = None) -> TwoPostAdvice:
    """Post moves for a two-post bridge from the 12th-fret action of strings 6 and 1.

    The wanted saddle-height change at each outer string is ``SADDLE_RATIO`` times its action error. The outer
    strings sit ``a = (P - span) / 2`` inside each post, so a bass-post move ``b`` and a treble-post move ``t``
    change string 6 by ``b (P - a)/P + t a/P`` and string 1 by ``b a/P + t (P - a)/P``; that 2x2 system is solved
    for ``b`` and ``t``. ``middle`` holds optional measured values of strings 5..2.
    """
    spacing, span = float(preset.post_spacing_mm), float(preset.bridge_span_mm)
    if spacing <= span:
        raise ValueError("the post spacing must be larger than the string span at the bridge")
    targets = action_targets(preset)
    err6, err1 = _validated(measured_6) - targets[6], _validated(measured_1) - targets[1]
    want6, want1 = -SADDLE_RATIO * err6, -SADDLE_RATIO * err1
    a = (spacing - span) / 2
    near, far = (spacing - a) / spacing, a / spacing
    det = near * near - far * far
    bass = (want6 * near - want1 * far) / det
    treble = (want1 * near - want6 * far) / det
    bass_move, bass_mm = _post_move(bass, tolerance_mm)
    treble_move, treble_mm = _post_move(treble, tolerance_mm)
    new6, new1 = targets[6], targets[1]  # the full move brings both outer strings to their targets
    expected = {s: new6 + (new1 - new6) * (6 - s) / 5 for s in STRINGS}
    mismatch = {}
    for string, value in (middle or {}).items():
        if string in (6, 1):
            continue
        if string not in expected:
            raise ValueError(f"strings are numbered 1 to 6, got {string}")
        mismatch[string] = _validated(value) - expected[string]
    return TwoPostAdvice(bass_move, bass_mm, treble_move, treble_mm, expected, mismatch)
