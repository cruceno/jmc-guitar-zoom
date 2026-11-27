import numpy as np
import pytest

from audio_signals import SR, cents, feed_in_blocks, pluck, silence, sine
from jmc_guitar_zoom.audio.pitch import PitchTracker, estimate_pitch, nearest_note

STRINGS = {"E2": 82.407, "A2": 110.0, "D3": 146.832, "G3": 195.998, "B3": 246.942, "E4": 329.628}


def test_nearest_note_names_the_note_its_octave_and_the_cents():
    assert nearest_note(440.0) == ("A", 4, pytest.approx(0.0, abs=1e-9))
    name, octave, off = nearest_note(445.0)
    assert (name, octave) == ("A", 4) and off == pytest.approx(19.56, abs=0.01)
    name, octave, off = nearest_note(82.407)
    assert (name, octave) == ("E", 2) and abs(off) < 0.05
    name, octave, off = nearest_note(261.0)  # a C4 a bit flat
    assert (name, octave) == ("C", 4) and off == pytest.approx(-4.14, abs=0.05)


def test_nearest_note_follows_the_reference_pitch():
    name, octave, off = nearest_note(442.0, reference=442.0)
    assert (name, octave) == ("A", 4) and off == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("freq", [82.407, 110.0, 196.0, 329.63, 659.26])
def test_estimate_pitch_finds_a_sine_within_a_tenth_of_a_cent(freq):
    frame = sine(freq, 0.1)[:4096]
    assert abs(cents(estimate_pitch(frame, SR), freq)) < 0.1


def test_estimate_pitch_returns_none_without_a_periodic_signal():
    assert estimate_pitch(silence(0.1)[:4096], SR) is None
    noise = np.random.default_rng(3).normal(scale=0.3, size=4096).astype(np.float32)
    assert estimate_pitch(noise, SR) is None


@pytest.mark.parametrize("fret", [0, 12])
@pytest.mark.parametrize("name", list(STRINGS))
def test_a_settled_pluck_reads_within_one_cent(name, fret):
    note, truth = pluck(STRINGS[name] * 2 ** (fret / 12), dur=1.6, seed=list(STRINGS).index(name) * 10 + fret)
    tracker = PitchTracker(SR)
    stable = [r for r in feed_in_blocks(tracker, note) if r.stable]
    assert stable, "the note never settled"
    assert abs(cents(stable[-1].frequency, truth)) <= 1.0
    assert stable[-1].note == ("E" if name.startswith("E") else name[0])


def test_the_attack_is_never_reported_as_stable():
    note, _ = pluck(110.0, dur=1.2, glide=6.0)
    tracker = PitchTracker(SR)
    readings = feed_in_blocks(tracker, np.concatenate([silence(0.3), note]))
    early = [r for r in readings if 0.3 <= r.time < 0.3 + tracker.attack_seconds]
    assert early and not any(r.stable for r in early)


def test_a_reading_carries_note_and_cents_against_the_reference():
    tracker = PitchTracker(SR)
    readings = feed_in_blocks(tracker, sine(445.0, 1.2))
    last = readings[-1]
    assert last.stable and last.note == "A" and last.octave == 4
    assert last.cents == pytest.approx(19.56, abs=0.2)


def test_silence_gives_no_pitch_and_no_stability():
    tracker = PitchTracker(SR)
    readings = feed_in_blocks(tracker, silence(0.6))
    assert readings and all(r.frequency is None and not r.stable for r in readings)
    assert readings[-1].level_db < -90


def test_level_and_clipping_are_reported():
    tracker = PitchTracker(SR)
    half = feed_in_blocks(tracker, sine(220.0, 0.5, amplitude=0.5))[-1]
    assert half.level_db == pytest.approx(-6.0, abs=0.3) and not half.clipping
    full = feed_in_blocks(tracker, np.clip(sine(220.0, 0.5, amplitude=1.4), -1.0, 1.0))[-1]
    assert full.clipping


def test_a_new_pluck_or_a_new_note_starts_a_new_note_id():
    first, _ = pluck(110.0, dur=1.0, seed=1)
    again, _ = pluck(110.0, dur=1.0, seed=2)
    octave, _ = pluck(220.0, dur=1.0, seed=3, peak=0.05)  # quieter than the ringing note: no level jump
    tracker = PitchTracker(SR)
    ids = []
    for part in (first, again):
        ids.append(feed_in_blocks(tracker, part)[-1].note_id)
    blend = octave.copy()  # the open string fades out under the fretted note
    tail = again[int(0.5 * SR):] * 0.05
    blend[:tail.size] += tail
    ids.append(feed_in_blocks(tracker, blend)[-1].note_id)
    assert ids[0] < ids[1] < ids[2]


@pytest.mark.parametrize("rate", [44100, 96000])
def test_other_sample_rates_work(rate):
    note, truth = pluck(146.832, dur=1.6, sr=rate)
    tracker = PitchTracker(rate)
    stable = [r for r in feed_in_blocks(tracker, note, block=rate // 50) if r.stable]
    assert stable and abs(cents(stable[-1].frequency, truth)) <= 1.0


def test_readings_count_time_from_the_samples_fed():
    tracker = PitchTracker(SR)
    readings = feed_in_blocks(tracker, sine(220.0, 1.0))
    assert readings[-1].time == pytest.approx(1.0, abs=0.03)
