"""Neck relief (the forward bow of the neck): compare a measure with the target and say how to turn the truss rod."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

MAX_RELIEF_MM = 2.0
MAX_TURN_FRACTION = 1 / 8  # never more than an eighth of a turn per step: retune, wait, measure again


class ReliefMove(Enum):
    OK = "ok"
    TIGHTEN = "tighten"  # too much relief: clockwise, seen from the nut's end
    LOOSEN = "loosen"  # too little relief: counter-clockwise


@dataclass(frozen=True)
class ReliefAdvice:
    move: ReliefMove
    error_mm: float  # measured - target; positive means too much relief
    turn_fraction: float  # of a full turn; 0 when OK
    clockwise: bool | None  # seen from the nut's end; None when OK


def _check(value: float, what: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0 or value > MAX_RELIEF_MM:
        raise ValueError(f"{what} must be between 0 and {MAX_RELIEF_MM} mm, got {value}")
    return value


def relief_advice(measured_mm: float, target_mm: float, tolerance_mm: float = 0.05) -> ReliefAdvice:
    """Compare the measured relief with the target; at most 1/8 turn per step, then retune and wait."""
    measured = _check(measured_mm, "the measured relief")
    target = _check(target_mm, "the target relief")
    error = round(measured - target, 6)
    if abs(error) <= tolerance_mm:
        return ReliefAdvice(ReliefMove.OK, error, 0.0, None)
    if error > 0:
        return ReliefAdvice(ReliefMove.TIGHTEN, error, MAX_TURN_FRACTION, True)
    return ReliefAdvice(ReliefMove.LOOSEN, error, MAX_TURN_FRACTION, False)
