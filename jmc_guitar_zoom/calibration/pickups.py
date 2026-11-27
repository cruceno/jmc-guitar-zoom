"""Pickup height advice, pluck-level balance between strings and positions, and the magnetic-pull detector."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from jmc_guitar_zoom.audio.pitch import PitchReading

from .presets import GuitarPreset

MAX_PICKUP_MM = 10.0
LEVEL_WINDOW_SECONDS = 0.3
MIN_LEVEL_DB = -60.0
STRING_TOLERANCE_CENTS = 60.0
PITCH_CHECK_SECONDS = 0.12  # the first hops of a pluck can read a wild pitch: judge the string after them
BALANCE_TOLERANCE_DB = 2.0
BASS_STRINGS = (6, 5, 4)
TREBLE_STRINGS = (3, 2, 1)
OPEN_STRING_HZ = {6: 82.407, 5: 110.0, 4: 146.832, 3: 195.998, 2: 246.942, 1: 329.628}  # standard tuning, A4 = 440

MAGNETIC_PULL_SKIP_SECONDS = 0.35
MAGNETIC_PULL_MEDIAN = 5
# Calibrated on synthetic plucks through PitchTracker (2.5 s, 48 kHz): 24 clean plucks of E2, A2 and D3 leave a
# residual peak-to-peak of 0.5-2.7 cents; a +-3 cent, 4 Hz modulation leaves 4.8-6.7 cents (E2 6.7, A2 4.8, D3 5.2)
# and +-2 cents leaves 3.6-4.7. The tracker's own smoothing shrinks the 6 cents peak-to-peak of the modulation.
MAGNETIC_PULL_WARN_CENTS = 4.0


class PickupMove(Enum):
    OK = "ok"
    RAISE = "raise"  # raise the pickup on that side
    LOWER = "lower"  # lower the pickup on that side


@dataclass(frozen=True)
class PickupAdvice:
    position: str
    side: str  # "bass" or "treble"
    string: int  # the string fretted at the last fret for this measure
    target_mm: float
    measured_mm: float
    error_mm: float  # measured - target; positive means too close to the string
    move: PickupMove


def pickup_advice(position: str, measured_bass_mm: float, measured_treble_mm: float, preset: GuitarPreset,
                  tolerance_mm: float = 0.2) -> dict[str, PickupAdvice]:
    """Per side ("bass", "treble"): raise or lower the pickup on that side, or OK.

    Heights are measured with the string fretted at the last fret, from the pole top to the string underside.
    """
    target = preset.target_for(position)
    result: dict[str, PickupAdvice] = {}
    for side, string, wanted, value in (("bass", target.bass_string, target.bass_mm, measured_bass_mm),
                                        ("treble", target.treble_string, target.treble_mm, measured_treble_mm)):
        value = float(value)
        if not math.isfinite(value) or value < 0 or value > MAX_PICKUP_MM:
            raise ValueError(f"the pickup height must be between 0 and {MAX_PICKUP_MM} mm, got {value}")
        error = round(value - wanted, 6)
        if abs(error) <= tolerance_mm:
            move = PickupMove.OK
        else:
            move = PickupMove.LOWER if error > 0 else PickupMove.RAISE
        result[side] = PickupAdvice(position, side, string, wanted, value, error, move)
    return result


@dataclass(frozen=True)
class PluckRefusal:
    """A note that is not the open string asked for."""

    note_id: int
    string: int
    cents: float  # heard pitch against the asked open string


@dataclass
class _Note:
    string: int
    start: float
    refused: bool = False
    checked: bool = False
    best: float = -math.inf
    recorded: bool = False


class PluckLevels:
    """Records one level per open-string pluck: the peak ``level_db`` in the first 0.3 s of the note.

    Feed it every ``PitchReading`` together with the string the user was asked to pluck. The string is judged on
    the first reading with a pitch that is stable or at least ``PITCH_CHECK_SECONDS`` into the note (the attack
    can read a wild pitch), while the attack's level still counts. A note whose pitch is not that string's open
    note (standard tuning, +-60 cents) is refused and records nothing: ``add`` returns a ``PluckRefusal`` once.
    """

    def __init__(self) -> None:
        self.levels: dict[int, list[float]] = {}
        self._note_id: int | None = None
        self._note: _Note | None = None

    def clear(self) -> None:
        self.levels = {}
        self._note_id = None
        self._note = None

    def add(self, reading: PitchReading, string: int) -> PluckRefusal | None:
        if string not in OPEN_STRING_HZ:
            raise ValueError(f"strings are numbered 1 to 6, got {string}")
        if reading.note_id != self._note_id or self._note is None:
            self._note_id = reading.note_id
            self._note = _Note(string, reading.time)
        note = self._note
        if note.refused:
            return None
        elapsed = reading.time - note.start
        if elapsed <= LEVEL_WINDOW_SECONDS:
            note.best = max(note.best, reading.level_db)
        refusal = None
        if not note.checked:
            if reading.frequency is None or (elapsed < PITCH_CHECK_SECONDS and not reading.stable):
                return None
            note.checked = True
            cents = 1200 * math.log2(reading.frequency / OPEN_STRING_HZ[note.string])
            if abs(cents) > STRING_TOLERANCE_CENTS:
                note.refused = True
                return PluckRefusal(reading.note_id, note.string, cents)
        if note.best >= MIN_LEVEL_DB:
            rounds = self.levels.setdefault(note.string, [])
            if note.recorded:
                rounds[-1] = note.best
            else:
                rounds.append(note.best)
                note.recorded = True
        return refusal


@dataclass(frozen=True)
class StringLevel:
    mean_db: float
    relative_db: float  # against the mean of the strings' means
    sd_db: float | None  # sample SD (ddof=1) over the rounds; None with a single round
    rounds: int


class BalanceAdvice(Enum):
    OK = "ok"
    BASS_LOUDER = "bass_louder"  # lower the bass side or raise the treble side
    TREBLE_LOUDER = "treble_louder"  # lower the treble side or raise the bass side


@dataclass(frozen=True)
class BalanceResult:
    strings: dict[int, StringLevel]
    mean_db: float
    bass_minus_treble_db: float | None  # None unless both sides have a string
    advice: BalanceAdvice | None


def balance(levels_by_string: Mapping[int, Sequence[float]]) -> BalanceResult:
    """Per-string level statistics and the bass (6, 5, 4) versus treble (3, 2, 1) side balance."""
    means = {s: float(np.mean(v)) for s, v in levels_by_string.items() if len(v)}
    if not means:
        raise ValueError("no levels to balance")
    overall = float(np.mean(list(means.values())))
    strings = {}
    for s, mean in means.items():
        values = levels_by_string[s]
        sd = float(np.std(values, ddof=1)) if len(values) > 1 else None
        strings[s] = StringLevel(mean, mean - overall, sd, len(values))
    bass = [means[s] for s in BASS_STRINGS if s in means]
    treble = [means[s] for s in TREBLE_STRINGS if s in means]
    if not bass or not treble:
        return BalanceResult(strings, overall, None, None)
    diff = float(np.mean(bass) - np.mean(treble))
    if round(abs(diff), 6) <= BALANCE_TOLERANCE_DB:
        advice = BalanceAdvice.OK
    else:
        advice = BalanceAdvice.BASS_LOUDER if diff > 0 else BalanceAdvice.TREBLE_LOUDER
    return BalanceResult(strings, overall, diff, advice)


@dataclass(frozen=True)
class PositionBalance:
    relative_db: dict[str, float]  # against the loudest position (<= 0)
    flagged: tuple[str, ...]  # positions more than 2 dB under the loudest


def position_balance(mean_by_position: Mapping[str, float]) -> PositionBalance:
    if not mean_by_position:
        raise ValueError("no positions to compare")
    loudest = max(mean_by_position.values())
    relative = {p: float(v) - loudest for p, v in mean_by_position.items()}
    flagged = tuple(p for p, v in relative.items() if round(-v, 6) > BALANCE_TOLERANCE_DB)
    return PositionBalance(relative, flagged)


@dataclass(frozen=True)
class MagneticPullResult:
    peak_to_peak_cents: float  # of the pitch residual after smoothing and removing the slow drift
    warn: bool
    enough_data: bool
    samples: int = 0
    threshold_cents: float = field(default=MAGNETIC_PULL_WARN_CENTS)


def magnetic_pull(readings: Sequence[PitchReading]) -> MagneticPullResult:
    """Look for a pitch wobble in the readings of one sustained note (a pickup too close pulls the string).

    Skips the first 0.35 s after the first reading, smooths the cents trace with a moving median of 5, removes
    a linear trend (a slow drift is normal) and reports the residual peak-to-peak; warns above 4 cents.
    """
    if not readings:
        return MagneticPullResult(0.0, False, False)
    start = readings[0].time + MAGNETIC_PULL_SKIP_SECONDS
    kept = [r for r in readings if r.time >= start and r.cents is not None]
    if len(kept) < MAGNETIC_PULL_MEDIAN * 2:
        return MagneticPullResult(0.0, False, False, len(kept))
    t = np.array([r.time for r in kept])
    c = np.array([r.cents for r in kept], dtype=float)
    smooth = np.median(np.lib.stride_tricks.sliding_window_view(c, MAGNETIC_PULL_MEDIAN), axis=1)
    ts = np.median(np.lib.stride_tricks.sliding_window_view(t, MAGNETIC_PULL_MEDIAN), axis=1)
    slope, offset = np.polyfit(ts, smooth, 1)
    residual = smooth - (slope * ts + offset)
    p2p = float(np.max(residual) - np.min(residual))
    return MagneticPullResult(p2p, p2p > MAGNETIC_PULL_WARN_CENTS, True, len(kept))
