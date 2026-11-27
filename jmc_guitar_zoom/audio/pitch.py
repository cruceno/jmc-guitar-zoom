"""Pitch of a monophonic note from audio samples (no Qt): YIN, the attack skipped and a settled flag.

A plucked string starts a few cents sharp and settles within a few hundred milliseconds, so the tracker
ignores ``attack_seconds`` after each new note and only calls a note *stable* once the readings of the
last ``settle_seconds`` agree (median absolute deviation within ``STABLE_MAD_CENTS``, none further than
``STABLE_SPREAD_CENTS``). The stable frequency is their median.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
A4 = 440.0
F_MIN = 60.0  # below a drop-C low string
F_MAX = 1400.0  # above the 24th fret of the high E string
YIN_THRESHOLD = 0.12
SILENT_PEAK = 1e-4  # -80 dBFS: no pitch in a frame this quiet

GATE_DB = -60.0  # window RMS below this: no note
ONSET_DB = 6.0  # a hop this much louder than the previous one is a new pluck
NEW_NOTE_CENTS = 35.0  # two frames in a row this far from the note: a new note without a pluck
STABLE_MAD_CENTS = 0.8  # median absolute deviation of the settle window: jitter allowed, drift not
STABLE_SPREAD_CENTS = 5.0  # and no reading of the window further than this from its median
CLIP_LEVEL = 0.99
REFINE_CUTOFF = 3.0  # the refining low-pass keeps the first three partials


class NoteName(NamedTuple):
    name: str
    octave: int
    cents: float


def cents_between(frequency: float, reference: float) -> float:
    return 1200.0 * math.log2(frequency / reference)


def nearest_note(frequency: float, reference: float = A4) -> NoteName:
    """The equal-tempered note nearest to ``frequency`` and how many cents it is away from it."""
    midi = 69.0 + 12.0 * math.log2(frequency / reference)
    nearest = round(midi)
    return NoteName(NOTE_NAMES[nearest % 12], nearest // 12 - 1, (midi - nearest) * 100.0)


def estimate_pitch(frame: np.ndarray, sample_rate: int, fmin: float = F_MIN, fmax: float = F_MAX,
                   threshold: float = YIN_THRESHOLD) -> float | None:
    """YIN fundamental frequency of one frame, with parabolic interpolation; None when it is not periodic."""
    x = np.asarray(frame, dtype=np.float64)
    if x.size < 64 or np.max(np.abs(x)) < SILENT_PEAK:
        return None
    n = x.size
    w = n // 2
    tau_max = min(int(sample_rate / fmin), n - w - 1)
    tau_min = max(2, int(sample_rate / fmax))
    if tau_max <= tau_min + 2:
        return None
    size = 1 << (2 * n - 1).bit_length()
    head = np.fft.rfft(x[:w], size)
    whole = np.fft.rfft(x, size)
    acf = np.fft.irfft(np.conj(head) * whole, size)[:tau_max + 2]  # r(tau) = sum_{j<w} x_j x_{j+tau}
    energy = np.concatenate(([0.0], np.cumsum(x * x)))
    taus = np.arange(tau_max + 2)
    diff = energy[w] + energy[w + taus] - energy[taus] - 2.0 * acf
    diff[0] = 0.0
    np.maximum(diff, 0.0, out=diff)
    running = np.cumsum(diff[1:])
    cmnd = np.ones_like(diff)
    cmnd[1:] = diff[1:] * taus[1:] / np.maximum(running, 1e-20)
    below = np.nonzero(cmnd[tau_min:tau_max + 1] < threshold)[0]
    if below.size == 0:
        return None
    tau = int(below[0]) + tau_min
    while tau + 1 <= tau_max and cmnd[tau + 1] < cmnd[tau]:
        tau += 1
    a, b, c = diff[tau - 1], diff[tau], diff[tau + 1]
    denom = a - 2.0 * b + c
    shift = 0.5 * (a - c) / denom if denom > 0 else 0.0
    return sample_rate / (tau + max(-1.0, min(1.0, shift)))


def lowpass(frame: np.ndarray, sample_rate: int, cutoff: float, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth-magnitude low-pass of one frame (FFT, zero-padded against wrap-around)."""
    x = np.asarray(frame, dtype=np.float64)
    size = 1 << (2 * x.size - 1).bit_length()
    freqs = np.fft.rfftfreq(size, 1.0 / sample_rate)
    mask = 1.0 / np.sqrt(1.0 + (freqs / cutoff) ** (2 * order))
    return np.fft.irfft(np.fft.rfft(x, size) * mask, size)[:x.size]


def refined_pitch(frame: np.ndarray, sample_rate: int) -> float | None:
    """YIN, then YIN again on the frame low-passed at 3x that pitch.

    The upper partials of a string are sharp (inharmonicity) and pull a period estimate sharp; keeping
    the fundamental and the next two partials halves that bias. The refined value is used only when it
    agrees with the first one (it never trades a pitch for its octave).
    """
    coarse = estimate_pitch(frame, sample_rate)
    if coarse is None:
        return None
    fine = estimate_pitch(lowpass(frame, sample_rate, REFINE_CUTOFF * coarse), sample_rate)
    if fine is None or abs(cents_between(fine, coarse)) > NEW_NOTE_CENTS:
        return coarse
    return fine


@dataclass(frozen=True)
class PitchReading:
    """One analysis hop. ``frequency`` is the median of the settled readings when ``stable``."""

    frequency: float | None
    note: str | None
    octave: int | None
    cents: float | None  # from the nearest note, against the reference pitch
    stable: bool
    level_db: float  # peak of the hop, dBFS
    clipping: bool
    note_id: int  # grows with every new pluck or new note
    time: float  # seconds of audio fed so far


class PitchTracker:
    """Feed it blocks of mono float samples (-1..1); each complete hop yields a PitchReading."""

    attack_seconds = 0.35
    settle_seconds = 0.2

    def __init__(self, sample_rate: int, reference: float = A4) -> None:
        self.sample_rate = int(sample_rate)
        self.reference = float(reference)
        self.window = 1 << math.ceil(math.log2(self.sample_rate * 0.085))  # 4096 at 44.1/48 kHz
        self.hop = self.window // 4
        self.settle_frames = max(3, math.ceil(self.settle_seconds * self.sample_rate / self.hop))
        self.reset()

    def reset(self) -> None:
        self._buffer = np.zeros(self.window, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._fed = 0
        self._frames: list[float] = []
        self._candidate: float | None = None
        self._attack_until = 0.0
        self._note_id = 0
        self._previous_db = -math.inf

    def feed(self, samples) -> PitchReading | None:
        """Analyse every complete hop in ``samples`` (plus what was left over); the latest reading or None."""
        data = np.asarray(samples, dtype=np.float32).ravel()
        pending = np.concatenate((self._pending, data)) if self._pending.size else data
        reading = None
        start = 0
        while pending.size - start >= self.hop:
            reading = self._process(pending[start:start + self.hop])
            start += self.hop
        self._pending = pending[start:].copy()
        return reading

    def _new_note(self, now: float) -> None:
        self._note_id += 1
        self._frames.clear()
        self._candidate = None
        self._attack_until = now + self.attack_seconds

    def _process(self, hop: np.ndarray) -> PitchReading:
        self._buffer = np.concatenate((self._buffer[self.hop:], hop))
        self._fed += hop.size
        now = self._fed / self.sample_rate
        peak = float(np.max(np.abs(hop))) if hop.size else 0.0
        level_db = 20.0 * math.log10(max(peak, 1e-6))
        hop_db = 10.0 * math.log10(max(float(np.mean(hop.astype(np.float64) ** 2)), 1e-14))
        if hop_db > GATE_DB and hop_db - self._previous_db >= ONSET_DB:
            self._new_note(now)
        self._previous_db = hop_db
        window_db = 10.0 * math.log10(max(float(np.mean(self._buffer.astype(np.float64) ** 2)), 1e-14))
        frequency = None
        if self._fed >= self.window and window_db > GATE_DB:
            frequency = refined_pitch(self._buffer, self.sample_rate)
        if frequency is None:
            if window_db <= GATE_DB:
                self._frames.clear()
                self._candidate = None
            return self._reading(None, False, level_db, peak, now)
        if self._frames and abs(cents_between(frequency, float(np.median(self._frames[-5:])))) > NEW_NOTE_CENTS:
            if self._candidate is not None and abs(cents_between(frequency, self._candidate)) <= NEW_NOTE_CENTS:
                self._new_note(now)  # confirmed by a second frame: not a one-frame glitch
            else:
                self._candidate = frequency
                return self._reading(frequency, False, level_db, peak, now)
        self._candidate = None
        if now >= self._attack_until:
            self._frames.append(frequency)
            del self._frames[:-4 * self.settle_frames]
        recent = self._frames[-self.settle_frames:]
        if len(recent) == self.settle_frames:
            median = float(np.median(recent))
            deviations = [abs(cents_between(f, median)) for f in recent]
            if float(np.median(deviations)) <= STABLE_MAD_CENTS and max(deviations) <= STABLE_SPREAD_CENTS:
                return self._reading(median, True, level_db, peak, now)
        return self._reading(frequency, False, level_db, peak, now)

    def _reading(self, frequency: float | None, stable: bool, level_db: float, peak: float,
                 now: float) -> PitchReading:
        if frequency is None:
            return PitchReading(None, None, None, None, False, level_db, peak >= CLIP_LEVEL, self._note_id, now)
        name, octave, off = nearest_note(frequency, self.reference)
        return PitchReading(frequency, name, octave, off, stable, level_db, peak >= CLIP_LEVEL, self._note_id, now)
