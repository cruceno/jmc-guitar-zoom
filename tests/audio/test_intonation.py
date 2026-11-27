import pytest

import statistics
from math import sqrt

from jmc_guitar_zoom.audio.intonation import (
    DEFAULT_ROUNDS, STRINGS, T_95, Event, IntonationSession, ReferenceKind, Step, Verdict, interval_verdict,
    mean_interval, octave_offset, saddle_shift_mm, verdict)
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


E = 82.41  # the low E, Hz


class Player:
    """Plays notes into a session the way the tracker would: every note a new ``note_id``, held until captured."""

    def __init__(self, session):
        self.session, self.clock, self.note_id = session, Clock(), 0

    def note(self, freq, seconds=0.8):
        self.note_id += 1
        return hold(self.session, self.clock, freq, self.note_id, seconds)

    def round(self, open_hz=E, c=0.0, d=0.0):
        """One round: the open string, the harmonic ``c`` cents from 2x open, the fretted ``d`` cents from the harmonic."""
        harmonic = 2 * open_hz * 2 ** (c / 1200)
        self.note(open_hz)
        self.note(harmonic)
        self.note(harmonic * 2 ** (d / 1200))

    def string(self, d_values, c=0.0, open_cents=(), number=6):
        self.session.select(number)
        base = 2 ** ((STRINGS[6 - number].midi - 69) / 12) * 440.0
        for i, d in enumerate(d_values):
            jitter = open_cents[i] if i < len(open_cents) else 0.0
            self.round(base * 2 ** (jitter / 1200), c if not isinstance(c, (list, tuple)) else c[i], d)


def make(rounds=3, tolerance=1.0):
    session = IntonationSession(tolerance=tolerance, capture_seconds=0.4, rounds=rounds)
    return session, Player(session)


def test_the_rounds_default_to_five_and_are_clamped_between_three_and_ten():
    assert IntonationSession().rounds == DEFAULT_ROUNDS == 5
    assert [IntonationSession(rounds=n).rounds for n in (1, 3, 7, 10, 25)] == [3, 3, 7, 10, 10]
    session = IntonationSession()
    session.set_rounds(2)
    assert session.rounds == 3
    session.set_rounds(99)
    assert session.rounds == 10


def test_each_round_takes_the_open_string_then_the_harmonic_then_the_fretted_note_each_by_itself():
    session, play = make(rounds=3)
    hold(session, play.clock, E, 0, 0.2)  # a note that was already ringing before the string was chosen
    session.select(6)
    assert (session.string, session.round, session.step) == (6, 1, Step.OPEN)
    assert hold(session, play.clock, E, 0, 1.0) == []  # the old note never counts
    seen = []
    for round_number in (1, 2, 3):
        for step, freq in ((Step.OPEN, E), (Step.HARMONIC, 2 * E), (Step.FRETTED, 2 * E)):
            assert (session.round, session.step) == (round_number, step)
            events = play.note(freq)
            seen.append(events[-1])
            if step is not Step.FRETTED or round_number < 3:
                # the note still rings: it is ignored, only a new note counts
                assert hold(session, play.clock, freq, play.note_id, 0.6) == []
    assert seen[:3] == [Event.NOTE_CAPTURED] * 3 and seen[-1] is Event.RESULT
    assert session.step is Step.RESULT and 6 in session.results


def test_a_harmonic_or_fretted_note_that_is_not_the_octave_is_refused_once_with_an_event():
    session, play = make()
    session.select(6)
    play.note(E)
    assert play.note(E) == [Event.NOT_THE_OCTAVE]  # the open string again where the harmonic goes
    assert (session.round, session.step) == (1, Step.HARMONIC)
    assert hold(session, play.clock, E, play.note_id, 0.6) == []  # the same refused note is not refused again
    play.note(2 * E * 2 ** (20 / 1200))  # 20 cents away: still the harmonic
    assert session.step is Step.FRETTED
    assert play.note(3 * E) == [Event.NOT_THE_OCTAVE]  # a fifth above the octave, fretted
    assert play.note(2 * E * 2 ** (-49 / 1200))[-1] is Event.NOTE_CAPTURED
    assert (session.round, session.step) == (2, Step.OPEN)


def test_an_open_string_far_from_the_first_round_is_refused_from_round_two_on():
    session, play = make()
    session.select(5)
    play.note(110.0 * 2 ** (40 / 1200))  # round 1: whatever the open string sounds becomes the reference
    play.note(2 * 110.0 * 2 ** (40 / 1200))
    play.note(2 * 110.0 * 2 ** (40 / 1200))
    assert play.note(110.0 * 2 ** (95 / 1200)) == [Event.NOT_THE_OPEN_STRING]  # 55 cents from round 1
    assert (session.round, session.step) == (2, Step.OPEN)
    assert play.note(110.0 * 2 ** (-8 / 1200))[-1] is Event.NOTE_CAPTURED  # 48 cents away: accepted
    assert session.step is Step.HARMONIC


def test_every_round_gives_the_fretted_vs_harmonic_offset_the_fretted_vs_open_one_and_the_cross_check():
    session, play = make()
    play.string([2.0, -1.0, 3.0], c=[0.5, 1.0, -1.5], number=6)
    rounds = session.results[6].stats.rounds
    assert [r.offset for r in rounds] == pytest.approx([2.0, -1.0, 3.0], abs=1e-6)  # fretted vs harmonic: the verdict's
    assert [r.cross for r in rounds] == pytest.approx([0.5, 1.0, -1.5], abs=1e-6)  # harmonic vs 2x open
    assert [r.vs_open for r in rounds] == pytest.approx([2.5, 0.0, 1.5], abs=1e-6)  # fretted vs 2x open
    assert rounds[0].open_hz == pytest.approx(E, abs=0.01)


def test_the_touch_repeatability_is_the_sample_standard_deviation_of_each_note_type():
    session, play = make()
    play.string([0.0, 0.0, 0.0], c=[0.0, 3.0, -3.0], open_cents=[0.0, 2.0, -2.0])
    stats = session.results[6].stats
    assert stats.sd_open == pytest.approx(2.0, abs=1e-6)  # (0, +2, -2): sqrt(8 / 2), ddof=1
    # harmonics: 0, +3, -3 around 2x open (which moves by 0, +2, -2): (0, 5, -5)
    assert stats.sd_harmonic == pytest.approx(5.0, abs=1e-6)
    assert stats.sd_fretted == pytest.approx(5.0, abs=1e-6)


@pytest.mark.parametrize("n", [3, 10])
def test_the_mean_offset_has_a_student_t_95_percent_half_width(n):
    values = [1.0 + 0.2 * ((i * 7) % 5 - 2) for i in range(n)]
    session, play = make(rounds=n)
    play.string(values)
    stats = session.results[6].stats
    t = {3: 4.303, 10: 2.262}[n]
    assert T_95[n - 1] == t
    assert stats.mean == pytest.approx(statistics.mean(values), abs=1e-6)
    assert stats.half_width == pytest.approx(t * statistics.stdev(values) / sqrt(n), abs=1e-6)
    assert stats.n == n and session.results[6].offset == pytest.approx(stats.mean)


def test_the_t_table_is_the_two_sided_95_percent_one_for_two_to_nine_degrees_of_freedom():
    assert [T_95[k] for k in range(2, 10)] == [4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262]
    assert mean_interval([1.0, 1.0, 1.0]) == (1.0, 0.0)
    assert mean_interval([2.0]) == (2.0, None)  # no interval from a single take


@pytest.mark.parametrize("offsets, expected", [
    ([0.1, 0.0, -0.1], Verdict.OK),  # the whole interval is inside ±1
    ([3.0, 3.2, 2.8], Verdict.SHARP),  # the whole interval is above +1
    ([-3.0, -3.2, -2.8], Verdict.FLAT),
    ([2.0, 0.5, 3.5], Verdict.UNSURE),  # the mean is past ±1 but the interval (±3.7) crosses it
    ([0.5, -0.5, 0.3], Verdict.UNSURE),  # the mean is inside but the interval (±1.3) crosses the edge
])
def test_the_verdict_has_three_states_against_the_interval(offsets, expected):
    session, play = make()
    play.string(offsets)
    assert session.results[6].verdict(1.0) is expected


def test_the_verdict_follows_the_tolerance_and_compares_at_the_tenth_of_a_cent():
    session, play = make()
    play.string([3.0, 3.2, 2.8])
    result = session.results[6]
    assert result.verdict(1.0) is Verdict.SHARP and result.verdict(3.0) is Verdict.UNSURE
    assert result.verdict(4.0) is Verdict.OK
    assert interval_verdict(1.04, 0.0, 1.0) is Verdict.OK  # shown as «1,0»
    assert interval_verdict(-1.06, 0.0, 1.0) is Verdict.FLAT  # shown as «−1,1»
    assert interval_verdict(0.5, 0.5, 1.0) is Verdict.OK and interval_verdict(1.5, 0.5, 1.0) is Verdict.UNSURE
    assert interval_verdict(1.5, None, 1.0) is None  # no interval, no verdict


def test_the_saddle_move_comes_from_the_mean_offset():
    session, play = make()
    play.string([3.0, 3.2, 2.8])
    assert saddle_shift_mm(session.results[6].offset, 648.0) == pytest.approx(3.0 * 648 * 0.693147 / 1200, abs=1e-3)


@pytest.mark.parametrize("c, warns", [(2.0, True), (-2.0, True), (1.0, False), (1.5, False)])
def test_the_cross_check_warns_when_the_harmonic_and_the_open_string_disagree_past_one_and_a_half_cents(c, warns):
    session, play = make()
    play.string([0.0, 0.0, 0.0], c=c)
    assert session.results[6].stats.cross_warning is warns
    assert session.results[6].stats.mean_cross == pytest.approx(c, abs=1e-6)


def test_repeat_last_take_drops_the_previous_step_of_the_round_and_captures_it_again():
    session, play = make()
    assert session.repeat_last() is False  # nothing taken yet
    session.select(6)
    play.note(E)
    play.note(2 * E)  # the harmonic, which the player wants to take again
    assert (session.round, session.step) == (1, Step.FRETTED)
    assert session.repeat_last() is True
    assert (session.round, session.step) == (1, Step.HARMONIC)
    assert hold(session, play.clock, 2 * E, play.note_id, 0.6) == []  # a note that rang before the repeat never counts
    play.note(2 * E * 2 ** (1.0 / 1200))  # the harmonic again, 1 cent sharp
    assert (session.round, session.step) == (1, Step.FRETTED)
    play.note(2 * E * 2 ** (1.0 / 1200))
    play.round(d=0.0)
    play.round(d=0.0)
    assert session.step is Step.RESULT
    first = session.results[6].stats.rounds[0]
    assert first.harmonic_hz == pytest.approx(2 * E * 2 ** (1.0 / 1200))  # the repeated take replaced the first one
    assert first.offset == pytest.approx(0.0, abs=1e-6)


def test_repeat_last_take_goes_back_across_a_round_boundary_and_after_the_result():
    session, play = make()
    session.select(6)
    play.round(d=1.0)
    assert (session.round, session.step) == (2, Step.OPEN)
    assert session.repeat_last() is True
    assert (session.round, session.step) == (1, Step.FRETTED)  # the last step of the previous round
    play.note(2 * E * 2 ** (4.0 / 1200))  # the fretted note again, now 4 cents
    assert (session.round, session.step) == (2, Step.OPEN)
    play.round(d=1.0)
    play.round(d=1.0)
    assert session.step is Step.RESULT and session.results[6].stats.offsets == pytest.approx((4.0, 1.0, 1.0), abs=1e-6)
    assert session.repeat_last() is True
    assert (session.round, session.step) == (3, Step.FRETTED)
    play.note(2 * E * 2 ** (2.0 / 1200))
    assert session.step is Step.RESULT
    assert session.results[6].stats.offsets == pytest.approx((4.0, 1.0, 2.0), abs=1e-6)


def test_the_open_detune_follows_the_last_open_take():
    session, play = make()
    session.select(6)
    assert session.open_detune is None
    play.note(82.407 * 2 ** (12 / 1200))
    assert session.open_detune == pytest.approx(12.0, abs=0.05)
    session.repeat_last()
    assert session.open_detune is None


def test_measuring_again_restarts_from_round_one_and_next_skips_only_the_strings_in_tolerance():
    session, play = make()
    play.string([0.0, 0.0, 0.0], number=6)  # in tolerance
    play.string([-3.0, -3.1, -2.9], number=5)  # flat
    play.string([2.0, 0.5, 3.5], number=4)  # not conclusive: it is not in tolerance either
    assert [session.results[n].verdict(1.0) for n in (6, 5, 4)] == [Verdict.OK, Verdict.FLAT, Verdict.UNSURE]
    session.remeasure()
    assert (session.string, session.round, session.step) == (4, 1, Step.OPEN)
    assert session.results[4].verdict(1.0) is Verdict.UNSURE  # kept until it is measured again
    assert session.next_string() == 3  # unmeasured, after this one
    for number in (3, 2, 1):
        play.string([0.0, 0.0, 0.0], number=number)
    assert session.next_string() == 5  # wraps around to the first one that is not in tolerance
    play.string([0.0, 0.0, 0.0], number=5)
    assert session.next_string() == 4  # the unsure one still counts as not in tolerance
    play.string([0.0, 0.0, 0.0], number=4)
    assert session.next_string() is None


def test_the_current_stats_follow_the_rounds_taken_so_far():
    session, play = make()
    session.select(6)
    assert session.current_stats() is None
    play.round(d=1.0)
    assert session.current_stats().n == 1 and session.current_stats().half_width is None
    play.round(d=2.0)
    play.round(d=3.0)
    assert session.current_stats() is session.results[6].stats


def test_silence_or_a_lost_note_never_captures():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.4)
    session.select(3)
    assert hold(session, clock, None, 1, 1.0) == []
    assert session.step is Step.OPEN and session.progress == 0.0


def test_a_short_wobble_of_the_same_note_does_not_restart_the_capture():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.6)
    session.select(5)
    hold(session, clock, 110.0, 1, 0.4)
    hold(session, clock, 110.05, 1, 0.04, stable=False)  # under a cent away: skipped, not a restart
    assert session.progress > 0.5
    assert Event.NOTE_CAPTURED in hold(session, clock, 110.0, 1, 0.3)


def test_mostly_unsettled_readings_never_capture():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.6)
    session.select(5)
    for _ in range(40):  # one settled reading out of four, all of the same note
        hold(session, clock, 110.0, 1, HOP)
        hold(session, clock, 110.02, 1, 3 * HOP, stable=False)
    assert session.step is Step.OPEN


def test_the_verdict_uses_the_tenth_of_a_cent_the_screen_shows():
    assert verdict(1.04, 1.0) is Verdict.OK  # shown as «1,0»: it must not read «1,0 cents alto» with ±1
    assert verdict(-1.04, 1.0) is Verdict.OK
    assert verdict(1.06, 1.0) is Verdict.SHARP  # shown as «1,1»


def test_a_capture_recovers_once_the_last_capture_window_is_settled():
    clock = Clock()
    session = IntonationSession(capture_seconds=0.6)
    session.select(6)
    for _ in range(25):  # two seconds where only one reading in four is settled: no capture, no full bar
        hold(session, clock, 82.4, 1, HOP)
        hold(session, clock, 82.41, 1, 3 * HOP, stable=False)
    assert session.step is Step.OPEN and session.progress < 1.0
    assert Event.NOTE_CAPTURED in hold(session, clock, 82.4, 1, 0.7)  # the note settles again: captured
