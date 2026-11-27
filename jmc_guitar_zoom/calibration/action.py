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
