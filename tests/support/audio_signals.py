"""Synthetic guitar-like notes for the pitch tests: inharmonic partials, decay, attack glide and noise."""

from __future__ import annotations

import numpy as np

SR = 48000


def pluck(f0: float, dur: float = 2.0, sr: int = SR, *, inharmonicity: float = 6e-5, glide: float = 4.0,
          glide_tau: float = 0.25, snr_db: float = 40.0, peak: float = 0.5, seed: int = 1) -> tuple[np.ndarray, float]:
    """A plucked note at ``f0`` Hz; returns (samples as float32 in -1..1, the true fundamental in Hz).

    The partials are ``n * f0 * sqrt(1 + B n^2)``; the pitch starts ``glide`` cents sharp and settles with
    ``glide_tau`` seconds, as a real string does after a pluck. The fundamental partial is the true pitch.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(int(dur * sr)) / sr
    bend = 2 ** (glide * np.exp(-t / glide_tau) / 1200)
    x = np.zeros_like(t)
    for n in range(1, 16):
        fn = n * f0 * np.sqrt(1 + inharmonicity * n * n)
        if fn > sr / 2.2:
            break
        phase = 2 * np.pi * np.cumsum(fn * bend) / sr
        x += (1.0 / n) * np.exp(-t * (0.6 + 0.35 * n)) * np.sin(phase + rng.uniform(0, 2 * np.pi))
    noise = rng.normal(size=t.size)
    noise *= np.sqrt(np.mean(x ** 2) / 10 ** (snr_db / 10)) / np.std(noise)
    x = x + noise
    x *= peak / np.max(np.abs(x))
    return x.astype(np.float32), f0 * np.sqrt(1 + inharmonicity)


def sine(freq: float, dur: float = 1.0, sr: int = SR, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(dur: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(dur * sr), dtype=np.float32)


def cents(a: float, b: float) -> float:
    return float(1200 * np.log2(a / b))


def feed_in_blocks(tracker, samples: np.ndarray, block: int = 960):
    """Feed ``samples`` the way an audio device delivers them (20 ms blocks at 48 kHz); return every reading."""
    readings = []
    for i in range(0, samples.size, block):
        reading = tracker.feed(samples[i:i + block])
        if reading is not None:
            readings.append(reading)
    return readings
