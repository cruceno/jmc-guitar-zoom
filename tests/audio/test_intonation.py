import pytest

from jmc_guitar_zoom.audio.intonation import (
    STRINGS, Event, IntonationSession, ReferenceKind, Step, Verdict, octave_offset, saddle_shift_mm, verdict)
from jmc_guitar_zoom.audio.pitch import PitchReading, nearest_note

HOP = 0.02  # seconds between readings, as the tracker delivers them


class Clock:
    def __init__(self):
        self.t = 0.0


def reading(clock, freq, note_id, stable=True):
    clock.t += HOP
    if freq is None:
        return PitchReading(None, None, None, None, False, -100.0, False, note_id, clock.t)
    name, octave, off = nearest_note(freq)
    return PitchReading(freq, name, octave, off, stable, -12.0, False, note_id, clock.t)


def hold(session, clock, freq, note_id, seconds, stable=True):
    """Feed a note held for ``seconds``; return the events the session raised."""
    events = []
    for _ in range(round(seconds / HOP)):
        event = session.feed(reading(clock, freq, note_id, stable))
        if event is not None:
            events.append(event)
    return events


def test_the_strings_are_numbered_six_to_one_in_standard_tuning():
    assert [(s.number, s.name, s.octave) for s in STRINGS] == [
        (6, "E", 2), (5, "A", 2), (4, "D", 3), (3, "G", 3), (2, "B", 3), (1, "E", 4)]


def test_octave_offset_compares_the_fretted_note_with_the_octave_of_the_reference():
    assert octave_offset(110.0, 220.0 * 2 ** (3 / 1200)) == pytest.approx(3.0, abs=1e-9)
    assert octave_offset(110.0, 220.0 * 2 ** (-2.5 / 1200), ReferenceKind.OPEN) == pytest.approx(-2.5, abs=1e-9)
    # a 12th-fret harmonic already sounds the octave: the fretted note must match it
    assert octave_offset(220.0, 220.0 * 2 ** (-2 / 1200), ReferenceKind.HARMONIC) == pytest.approx(-2.0, abs=1e-9)


def test_verdict_uses_the_tolerance_both_ways():
    assert verdict(0.9, 1.0) is Verdict.OK
    assert verdict(-1.0, 1.0) is Verdict.OK
    assert verdict(1.2, 1.0) is Verdict.SHARP
    assert verdict(-1.5, 1.0) is Verdict.FLAT
    assert verdict(1.5, 2.0) is Verdict.OK


def test_saddle_shift_lengthens_a_sharp_string_and_shortens_a_flat_one():
    assert saddle_shift_mm(1.0, 648.0) == pytest.approx(0.3743, abs=1e-4)  # positive: away from the neck
    assert saddle_shift_mm(-2.0, 628.0) == pytest.approx(-0.7255, abs=1e-4)  # negative: toward the neck


def test_a_guided_measurement_of_one_string():
    clock = Clock()
    session = IntonationSession(tolerance=1.0, capture_seconds=0.8)
    hold(session, clock, 82.5, 0, 0.2)  # a note that was already ringing before the string was chosen
    session.select(6)
    assert session.string == 6 and session.step is Step.REFERENCE
    assert hold(session, clock, 82.5, 0, 1.0) == []  # the old note never counts
    events = hold(session, clock, 82.5, 1, 1.0)
    assert Event.REFERENCE_CAPTURED in events
    assert session.step is Step.FRETTED and session.reference_hz == pytest.approx(82.5)
    assert hold(session, clock, 82.5, 1, 1.0) == []  # the open string still rings: ignored
    assert hold(session, clock, 82.5, 2, 1.0) == [Event.NOT_THE_OCTAVE]  # the open string plucked again, once
    events = hold(session, clock, 165.0 * 2 ** (2 / 1200), 3, 1.0)
    assert events[-1] is Event.RESULT and session.step is Step.RESULT
    result = session.results[6]
    assert result.offset == pytest.approx(2.0, abs=1e-6)
    assert result.verdict is Verdict.SHARP
    assert result.reference_hz == pytest.approx(82.5) and result.fretted_hz == pytest.approx(165.0 * 2 ** (2 / 1200))


def test_the_capture_needs_the_note_settled_for_the_whole_capture_time():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.8)
    session.select(5)
    assert hold(session, clock, 110.0, 1, 0.5) == []
    assert session.progress == pytest.approx(0.5 / 0.8, abs=0.05)
    hold(session, clock, 110.3, 1, 0.04, stable=False)  # the reading wobbled: start again
    assert session.progress == 0.0
    assert hold(session, clock, 110.0, 1, 0.5) == []
    assert Event.REFERENCE_CAPTURED in hold(session, clock, 110.0, 1, 0.4)


def test_the_captured_frequency_is_the_median_of_the_settled_readings():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.4)
    session.select(5)
    for freq in [110.0, 110.02, 109.98, 110.01, 109.99] * 5:
        session.feed(reading(clock, freq, 1))
    assert session.reference_hz == pytest.approx(110.0, abs=0.011)


def test_a_harmonic_reference_expects_the_same_pitch_on_the_fret():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.4, reference_kind=ReferenceKind.HARMONIC)
    session.select(4)
    hold(session, clock, 293.66, 1, 0.6)
    assert session.step is Step.FRETTED
    assert hold(session, clock, 293.66 * 2 ** (-1.5 / 1200), 2, 0.6)[-1] is Event.RESULT
    assert session.results[4].verdict is Verdict.FLAT


def test_the_reference_detune_says_how_far_the_open_string_is_from_its_note():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.4)
    session.select(6)
    hold(session, clock, 82.407 * 2 ** (12 / 1200), 1, 0.6)
    assert session.reference_detune == pytest.approx(12.0, abs=0.05)


def test_measuring_again_restarts_the_string_and_next_skips_strings_in_tolerance():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.4)
    session.select(6)
    hold(session, clock, 82.4, 1, 0.6)
    hold(session, clock, 164.8, 2, 0.6)  # exactly the octave: in tolerance
    assert session.results[6].verdict is Verdict.OK
    session.select(5)
    hold(session, clock, 110.0, 3, 0.6)
    hold(session, clock, 220.0 * 2 ** (-3 / 1200), 4, 0.6)
    assert session.results[5].verdict is Verdict.FLAT
    session.remeasure()
    assert session.string == 5 and session.step is Step.REFERENCE
    assert session.results[5].verdict is Verdict.FLAT  # kept until it is measured again
    assert session.next_string() == 4  # the first string, low to high, after this one that is not in tolerance
    note_ids = iter(range(10, 30))
    for number in (4, 3, 2, 1):
        session.select(number)
        base = 2 ** ((STRINGS[6 - number].midi - 69) / 12) * 440.0
        hold(session, clock, base, next(note_ids), 0.6)
        hold(session, clock, 2 * base, next(note_ids), 0.6)
    assert session.next_string() == 5  # wraps around to the one still out of tolerance
    session.select(5)
    hold(session, clock, 110.0, 30, 0.6)
    hold(session, clock, 220.0, 31, 0.6)
    assert session.next_string() is None  # all six in tolerance


def test_silence_or_a_lost_note_never_captures():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.4)
    session.select(3)
    assert hold(session, clock, None, 1, 1.0) == []
    assert session.step is Step.REFERENCE and session.progress == 0.0


def test_a_short_wobble_of_the_same_note_does_not_restart_the_capture():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.6)
    session.select(5)
    hold(session, clock, 110.0, 1, 0.4)
    hold(session, clock, 110.05, 1, 0.04, stable=False)  # under a cent away: skipped, not a restart
    assert session.progress > 0.5
    assert Event.REFERENCE_CAPTURED in hold(session, clock, 110.0, 1, 0.3)


def test_mostly_unsettled_readings_never_capture():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.6)
    session.select(5)
    for _ in range(40):  # one settled reading out of four, all of the same note
        hold(session, clock, 110.0, 1, HOP)
        hold(session, clock, 110.02, 1, 3 * HOP, stable=False)
    assert session.step is Step.REFERENCE
