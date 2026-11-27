"""Guided, statistical intonation (octavación) of a guitar, one string at a time (no Qt).

For each string the player repeats rounds of three notes: the open string, its 12th-fret harmonic and the string
fretted at the 12th. The fretted note should sound exactly the pitch of the harmonic (the octave of the open
string). When it is sharp the vibrating length is too short: the saddle moves away from the neck; when it is
flat the saddle moves toward the neck. Repeating the notes shows how reproducible the player's touch is first,
so the verdict compares the mean offset and its 95 % confidence interval with the tolerance instead of
"calibrating noise". Comparing readings of the same input makes the result independent of the reference pitch
and of the sound card's clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import numpy as np

from .pitch import A4, PitchReading, cents_between, nearest_note

WRONG_NOTE_CENTS = 50.0  # a fretted note this far from the expected pitch is another note
DEFAULT_TOLERANCE = 1.0
DEFAULT_CAPTURE_SECONDS = 0.6
DEPARTURE_CENTS = 3.0  # an unsettled reading this far from the captured median: the note moved, start again
MIN_STABLE_SHARE = 0.6  # settled readings must cover this share of the last capture_seconds
MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS = 3, 10, 5
CROSS_CHECK_CENTS = 1.5  # the harmonic and the open string may disagree this much before the player is warned
# Student t, two-sided 95 %, by degrees of freedom (rounds - 1); the rounds are 3 to 10
T_95 = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


class ReferenceKind(Enum):
    OPEN = "open"  # the open string: the 12th fret must sound its octave
    HARMONIC = "harmonic"  # the 12th-fret harmonic: the 12th fret must sound the same pitch


class Verdict(Enum):
    OK = "ok"
    SHARP = "sharp"  # move the saddle away from the neck
    FLAT = "flat"  # move the saddle toward the neck
    UNSURE = "unsure"  # the interval crosses the tolerance edge: repeat or improve the touch


class Step(Enum):
    OPEN = "open"
    HARMONIC = "harmonic"
    FRETTED = "fretted"
    RESULT = "result"


NOTE_STEPS = (Step.OPEN, Step.HARMONIC, Step.FRETTED)  # the order of the notes of a round


class Event(Enum):
    NOTE_CAPTURED = "note_captured"
    NOT_THE_OCTAVE = "not_the_octave"  # a harmonic or fretted note that is not the octave of the round's open string
    NOT_THE_OPEN_STRING = "not_the_open_string"  # an open string far from the first round's
    RESULT = "result"


@dataclass(frozen=True)
class GuitarString:
    number: int  # 6 = low E
    name: str
    octave: int
    midi: int


STRINGS = (
    GuitarString(6, "E", 2, 40), GuitarString(5, "A", 2, 45), GuitarString(4, "D", 3, 50),
    GuitarString(3, "G", 3, 55), GuitarString(2, "B", 3, 59), GuitarString(1, "E", 4, 64),
)
ORDER = tuple(s.number for s in STRINGS)


def octave_offset(reference_hz: float, fretted_hz: float, kind: ReferenceKind = ReferenceKind.OPEN) -> float:
    """Cents between the fretted 12th-fret note and the pitch it should have."""
    target = reference_hz * (2.0 if kind is ReferenceKind.OPEN else 1.0)
    return 1200.0 * math.log2(fretted_hz / target)


def verdict(offset: float, tolerance: float = DEFAULT_TOLERANCE) -> Verdict:
    """Judged at the tenth of a cent the screen shows, so «1,0 cents» never reads out of a ±1 tolerance."""
    if round(abs(offset), 1) <= tolerance + 1e-9:
        return Verdict.OK
    return Verdict.SHARP if offset > 0 else Verdict.FLAT


def saddle_shift_mm(offset: float, scale_mm: float) -> float:
    """Approximate saddle move that cancels ``offset``; positive: away from the neck (string longer).

    Lengthening the string by dL (and tuning it again) lowers the 12th fret against the open string by
    about 1200 / ln 2 * dL / L cents, so dL = offset * L * ln 2 / 1200: about 0.37 mm per cent at 648 mm.
    """
    return offset * scale_mm * math.log(2.0) / 1200.0


def mean_interval(values) -> tuple[float, float | None]:
    """The mean and the half-width of its 95 % confidence interval (Student t, n - 1); None under 3 values."""
    n = len(values)
    mean = float(np.mean(values))
    if n < MIN_ROUNDS:
        return mean, None
    return mean, T_95[n - 1] * float(np.std(values, ddof=1)) / math.sqrt(n)


def interval_verdict(mean: float, half_width: float | None, tolerance: float) -> Verdict | None:
    """In tolerance when the whole interval is inside it, to move when it is all outside, else not conclusive.

    Judged at the tenth of a cent the screen shows, so «1,0 cents» never reads out of a ±1 tolerance.
    """
    if half_width is None:
        return None
    centre, spread = round(abs(mean), 1), round(half_width, 1)
    if centre + spread <= tolerance + 1e-9:
        return Verdict.OK
    if centre - spread > tolerance + 1e-9:
        return Verdict.SHARP if mean > 0 else Verdict.FLAT
    return Verdict.UNSURE


@dataclass(frozen=True)
class Round:
    open_hz: float
    harmonic_hz: float
    fretted_hz: float

    @property
    def offset(self) -> float:
        """Cents of the fretted note against the harmonic: the verdict's offset (positive: the 12th fret is sharp)."""
        return octave_offset(self.harmonic_hz, self.fretted_hz, ReferenceKind.HARMONIC)

    @property
    def vs_open(self) -> float:
        """Cents of the fretted note against twice the open string."""
        return octave_offset(self.open_hz, self.fretted_hz, ReferenceKind.OPEN)

    @property
    def cross(self) -> float:
        """Cents of the harmonic against twice the open string: the cross-check."""
        return octave_offset(self.open_hz, self.harmonic_hz, ReferenceKind.OPEN)


def _spread(values_hz) -> float | None:
    """Sample standard deviation in cents of the takes of one note type around their own mean."""
    if len(values_hz) < 2:
        return None
    cents = [cents_between(f, values_hz[0]) for f in values_hz]
    return float(np.std(cents, ddof=1))


@dataclass(frozen=True)
class Stats:
    """What the rounds taken so far say: the paired offsets, the touch repeatability and the interval."""

    rounds: tuple[Round, ...]

    @property
    def n(self) -> int:
        return len(self.rounds)

    @property
    def offsets(self) -> tuple[float, ...]:
        return tuple(r.offset for r in self.rounds)

    @property
    def vs_open(self) -> tuple[float, ...]:
        return tuple(r.vs_open for r in self.rounds)

    @property
    def cross(self) -> tuple[float, ...]:
        return tuple(r.cross for r in self.rounds)

    @property
    def mean(self) -> float:
        return mean_interval(self.offsets)[0]

    @property
    def half_width(self) -> float | None:
        return mean_interval(self.offsets)[1]

    @property
    def mean_cross(self) -> float:
        return mean_interval(self.cross)[0]

    @property
    def cross_warning(self) -> bool:
        return round(abs(self.mean_cross), 1) > CROSS_CHECK_CENTS

    @property
    def sd_open(self) -> float | None:
        return _spread([r.open_hz for r in self.rounds])

    @property
    def sd_harmonic(self) -> float | None:
        return _spread([r.harmonic_hz for r in self.rounds])

    @property
    def sd_fretted(self) -> float | None:
        return _spread([r.fretted_hz for r in self.rounds])

    def verdict(self, tolerance: float) -> Verdict | None:
        return interval_verdict(self.mean, self.half_width, tolerance)


@dataclass(frozen=True)
class StringResult:
    number: int
    stats: Stats

    @property
    def offset(self) -> float:
        """The mean offset of the rounds, in cents."""
        return self.stats.mean

    def verdict(self, tolerance: float) -> Verdict:
        return self.stats.verdict(tolerance)


class IntonationSession:
    """The guided rounds for one string at a time, driven by the tracker's readings."""

    def __init__(self, tolerance: float = DEFAULT_TOLERANCE, capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
                 reference_pitch: float = A4, rounds: int = DEFAULT_ROUNDS) -> None:
        self.tolerance = tolerance
        self.capture_seconds = capture_seconds
        self.reference_pitch = reference_pitch
        self.rounds = _clamp_rounds(rounds)
        self.string: int | None = None
        self.step: Step | None = None
        self.results: dict[int, StringResult] = {}
        self.progress = 0.0
        self._notes: list[float] = []  # the captured notes of the string, in order: three per round
        self._last_id = -1
        self._entry_id = -1
        self._rejected_id: int | None = None
        self._accumulating: int | None = None
        self._captured: list[tuple[float, float]] = []  # (time, frequency) of the settled readings
        self._start: float | None = None
        self._hop = 0.0  # seconds between two readings, measured
        self._previous_time: float | None = None

    # ------------------------------------------------------------------ steps

    @property
    def round(self) -> int:
        """The round being taken, from 1 (the last one once the string is done)."""
        return min(self.rounds, len(self._notes) // 3 + 1)

    @property
    def open_detune(self) -> float | None:
        """Cents of the last captured open string from its nearest note."""
        opens = self._notes[0::3]
        return nearest_note(opens[-1], self.reference_pitch).cents if opens else None

    @property
    def can_repeat(self) -> bool:
        return bool(self._notes)

    def set_rounds(self, rounds: int) -> None:
        rounds = _clamp_rounds(rounds)
        if rounds != self.rounds:
            self.rounds = rounds
            if self.string is not None:
                self.select(self.string)

    def select(self, number: int) -> None:
        if number not in ORDER:
            raise ValueError(f"no string {number}")
        self.string = number
        self._notes = []
        self._enter(Step.OPEN)

    def remeasure(self) -> None:
        if self.string is not None:
            self.select(self.string)

    def repeat_last(self) -> bool:
        """Drop the last captured note (of this round, or the last one of the previous round) to take it again."""
        if self.string is None or not self._notes:
            return False
        self._notes.pop()
        self._enter(NOTE_STEPS[len(self._notes) % 3])
        return True

    def next_string(self) -> int | None:
        """The next string, low to high and wrapping around, that is unmeasured or not in tolerance."""
        start = ORDER.index(self.string) + 1 if self.string in ORDER else 0
        for i in range(len(ORDER)):
            number = ORDER[(start + i) % len(ORDER)]
            result = self.results.get(number)
            if result is None or result.verdict(self.tolerance) is not Verdict.OK:
                return number
        return None

    def current_stats(self) -> Stats | None:
        """The statistics of the rounds of the string taken so far (the result once it is done)."""
        if self.string is None:
            return None
        if self.step is Step.RESULT:
            return self.results[self.string].stats
        rounds = self._rounds()
        return Stats(rounds) if rounds else None

    def _rounds(self) -> tuple[Round, ...]:
        notes = self._notes
        return tuple(Round(*notes[i:i + 3]) for i in range(0, len(notes) - len(notes) % 3, 3))

    def _enter(self, step: Step) -> None:
        self.step = step
        self._entry_id = self._last_id  # only a note played from now on counts
        self._rejected_id = None
        self._reset_capture()

    def _reset_capture(self) -> None:
        self._accumulating = None
        self._captured = []
        self._start = None
        self.progress = 0.0

    def _captured_median(self) -> float:
        return float(np.median([f for _, f in self._captured]))

    def _wrong_note(self, frequency: float) -> Event | None:
        """The refusal for a note that is not the expected one, or None."""
        position = len(self._notes)
        if self.step is Step.OPEN:
            if position and abs(cents_between(frequency, self._notes[0])) > WRONG_NOTE_CENTS:
                return Event.NOT_THE_OPEN_STRING
            return None
        expected = 2.0 * self._notes[position - (1 if self.step is Step.HARMONIC else 2)]
        return Event.NOT_THE_OCTAVE if abs(cents_between(frequency, expected)) > WRONG_NOTE_CENTS else None

    # ------------------------------------------------------------------ readings

    def feed(self, reading: PitchReading) -> Event | None:
        self._last_id = reading.note_id
        if self._previous_time is not None and reading.time > self._previous_time:
            self._hop = reading.time - self._previous_time
        self._previous_time = reading.time
        if self.step in (None, Step.RESULT) or reading.note_id <= self._entry_id:
            return None
        if reading.frequency is None:  # the note was lost
            self._reset_capture()
            return None
        if reading.note_id != self._accumulating:
            self._reset_capture()
        if not reading.stable:
            # a short wobble of the same note is skipped; a real move (tuning, a bend) starts again
            if self._captured and abs(cents_between(reading.frequency, self._captured_median())) > DEPARTURE_CENTS:
                self._reset_capture()
            return None
        self._accumulating = reading.note_id
        if reading.note_id == self._rejected_id:
            return None
        refusal = self._wrong_note(reading.frequency)
        if refusal is not None:
            self._rejected_id = reading.note_id
            self._reset_capture()
            return refusal
        if self._start is None:
            self._start = reading.time
        self._captured.append((reading.time, reading.frequency))
        # only the last capture_seconds count: a note that wobbled for a while can still settle and be taken
        since = reading.time - self.capture_seconds - 1e-6
        self._captured = [(t, f) for t, f in self._captured if t >= since]
        elapsed = reading.time - self._start
        needed = MIN_STABLE_SHARE * self.capture_seconds
        settled = len(self._captured) * self._hop
        if self.capture_seconds <= 0:
            self.progress = 1.0
        else:
            self.progress = min(1.0, elapsed / self.capture_seconds, settled / needed if needed > 0 else 1.0)
        if elapsed + 1e-6 < self.capture_seconds or settled + 1e-9 < needed:
            return None
        self._notes.append(self._captured_median())
        if len(self._notes) < 3 * self.rounds:
            self._enter(NOTE_STEPS[len(self._notes) % 3])
            return Event.NOTE_CAPTURED
        self.results[self.string] = StringResult(self.string, Stats(self._rounds()))
        self._enter(Step.RESULT)
        return Event.RESULT


def _clamp_rounds(rounds: int) -> int:
    return max(MIN_ROUNDS, min(MAX_ROUNDS, int(rounds)))
