"""Guided intonation (octavación) of a guitar, one string at a time (no Qt).

For each string the player plays a reference (the open string, or its 12th-fret harmonic) and then the
note fretted at the 12th fret. The fretted note should be exactly the octave of the open string (or the
same pitch as the harmonic). When it is sharp the vibrating length is too short: the saddle moves away
from the neck; when it is flat the saddle moves toward the neck. Comparing two readings of the same
input makes the result independent of the reference pitch and of the sound card's clock.
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


class ReferenceKind(Enum):
    OPEN = "open"  # the open string: the 12th fret must sound its octave
    HARMONIC = "harmonic"  # the 12th-fret harmonic: the 12th fret must sound the same pitch


class Verdict(Enum):
    OK = "ok"
    SHARP = "sharp"  # move the saddle away from the neck
    FLAT = "flat"  # move the saddle toward the neck


class Step(Enum):
    REFERENCE = "reference"
    FRETTED = "fretted"
    RESULT = "result"


class Event(Enum):
    REFERENCE_CAPTURED = "reference_captured"
    NOT_THE_OCTAVE = "not_the_octave"
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


@dataclass(frozen=True)
class StringResult:
    number: int
    reference_hz: float
    fretted_hz: float
    offset: float  # cents; positive: the 12th fret is sharp
    verdict: Verdict


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


class IntonationSession:
    """The guided steps for one string at a time, driven by the tracker's readings."""

    def __init__(self, tolerance: float = DEFAULT_TOLERANCE, capture_seconds: float = DEFAULT_CAPTURE_SECONDS,
                 reference_kind: ReferenceKind = ReferenceKind.OPEN, reference_pitch: float = A4) -> None:
        self.tolerance = tolerance
        self.capture_seconds = capture_seconds
        self.reference_kind = reference_kind
        self.reference_pitch = reference_pitch
        self.string: int | None = None
        self.step: Step | None = None
        self.reference_hz: float | None = None
        self.reference_detune: float | None = None  # cents of the captured reference from its nearest note
        self.results: dict[int, StringResult] = {}
        self.progress = 0.0
        self._last_id = -1
        self._entry_id = -1
        self._rejected_id: int | None = None
        self._accumulating: int | None = None
        self._captured: list[tuple[float, float]] = []  # (time, frequency) of the settled readings
        self._start: float | None = None
        self._hop = 0.0  # seconds between two readings, measured
        self._previous_time: float | None = None

    # ------------------------------------------------------------------ steps

    def select(self, number: int) -> None:
        if number not in ORDER:
            raise ValueError(f"no string {number}")
        self.string = number
        self.reference_hz = None
        self.reference_detune = None
        self._enter(Step.REFERENCE)

    def remeasure(self) -> None:
        if self.string is not None:
            self.select(self.string)

    def next_string(self) -> int | None:
        """The next string, low to high and wrapping around, that is unmeasured or out of tolerance."""
        start = ORDER.index(self.string) + 1 if self.string in ORDER else 0
        for i in range(len(ORDER)):
            number = ORDER[(start + i) % len(ORDER)]
            result = self.results.get(number)
            if result is None or result.verdict is not Verdict.OK:
                return number
        return None

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

    # ------------------------------------------------------------------ readings

    def feed(self, reading: PitchReading) -> Event | None:
        self._last_id = reading.note_id
        if self._previous_time is not None and reading.time > self._previous_time:
            self._hop = reading.time - self._previous_time
        self._previous_time = reading.time
        if self.step not in (Step.REFERENCE, Step.FRETTED) or reading.note_id <= self._entry_id:
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
        if self.step is Step.FRETTED:
            if reading.note_id == self._rejected_id:
                return None
            off = octave_offset(self.reference_hz, reading.frequency, self.reference_kind)
            if abs(off) > WRONG_NOTE_CENTS:
                self._rejected_id = reading.note_id
                self._reset_capture()
                return Event.NOT_THE_OCTAVE
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
        captured = self._captured_median()
        if self.step is Step.REFERENCE:
            self.reference_hz = captured
            self.reference_detune = nearest_note(captured, self.reference_pitch).cents
            self._enter(Step.FRETTED)
            return Event.REFERENCE_CAPTURED
        offset = octave_offset(self.reference_hz, captured, self.reference_kind)
        self.results[self.string] = StringResult(self.string, self.reference_hz, captured, offset,
                                                 verdict(offset, self.tolerance))
        self._enter(Step.RESULT)
        return Event.RESULT
