import numpy as np
import pytest

from audio_signals import SR, feed_in_blocks, pluck
from jmc_guitar_zoom.audio.pitch import PitchReading, PitchTracker
from jmc_guitar_zoom.calibration import (FENDER_STYLE, GIBSON_STYLE, MAGNETIC_PULL_WARN_CENTS, BalanceAdvice,
                                         PickupMove, PluckLevels, balance, magnetic_pull, pickup_advice,
                                         position_balance)

OPEN = {6: 82.407, 5: 110.0, 4: 146.832, 3: 195.998, 2: 246.942, 1: 329.628}


def reading(freq, level_db, note_id, time):
    return PitchReading(freq, "E" if freq else None, 2 if freq else None, 0.0 if freq else None, False, level_db,
                        False, note_id, time)


# ---- pickup height ----

def test_a_pickup_too_close_on_one_side_is_lowered_there_and_the_other_side_is_ok():
    advice = pickup_advice("bridge", 3.0, 2.4, FENDER_STYLE)  # single coil: 3.2 / 2.4
    assert advice["bass"].move is PickupMove.OK
    assert advice["bass"].error_mm == pytest.approx(-0.2)
    assert advice["treble"].move is PickupMove.OK
    advice = pickup_advice("neck", 4.0, 1.5, FENDER_STYLE)
    assert advice["bass"].move is PickupMove.LOWER and advice["bass"].error_mm == pytest.approx(0.8)
    assert advice["bass"].target_mm == pytest.approx(3.2)
    assert advice["treble"].move is PickupMove.RAISE and advice["treble"].error_mm == pytest.approx(-0.9)


def test_the_target_depends_on_the_pickup_type_of_that_position():
    advice = pickup_advice("neck", 2.4, 1.6, GIBSON_STYLE)  # humbucker: 2.4 / 1.6
    assert advice["bass"].move is PickupMove.OK and advice["treble"].move is PickupMove.OK
    assert pickup_advice("neck", 3.2, 2.4, GIBSON_STYLE)["bass"].move is PickupMove.LOWER


def test_the_tolerance_edge_is_ok_and_a_custom_tolerance_is_honoured():
    assert pickup_advice("neck", 3.4, 2.4, FENDER_STYLE)["bass"].move is PickupMove.OK
    assert pickup_advice("neck", 3.45, 2.4, FENDER_STYLE)["bass"].move is PickupMove.LOWER
    assert pickup_advice("neck", 3.45, 2.4, FENDER_STYLE, tolerance_mm=0.5)["bass"].move is PickupMove.OK


@pytest.mark.parametrize("position,bass,treble", [("middle", 2.4, 1.6), ("neck", -1.0, 2.0), ("neck", 2.0, 15.0)])
def test_an_unknown_position_or_an_absurd_height_is_rejected(position, bass, treble):
    preset = GIBSON_STYLE
    with pytest.raises(ValueError):
        pickup_advice(position, bass, treble, preset)


# ---- pluck levels ----

def test_a_new_note_id_records_one_level_for_the_string_asked():
    levels = PluckLevels()
    levels.add(reading(82.4, -20.0, 1, 1.00), 6)
    levels.add(reading(82.4, -18.0, 1, 1.10), 6)
    levels.add(reading(82.4, -30.0, 1, 1.20), 6)
    levels.add(reading(82.4, -25.0, 2, 3.00), 6)
    assert levels.levels == {6: [-18.0, -25.0]}


def test_only_the_first_0_3_seconds_of_a_note_count():
    levels = PluckLevels()
    levels.add(reading(110.0, -22.0, 1, 1.00), 5)
    levels.add(reading(110.0, -15.0, 1, 1.29), 5)
    levels.add(reading(110.0, -5.0, 1, 1.31), 5)  # past 0.3 s: a later swell does not count
    assert levels.levels == {5: [-15.0]}


def test_notes_without_a_frequency_or_below_minus_60_dbfs_are_ignored():
    levels = PluckLevels()
    levels.add(reading(None, -20.0, 1, 1.0), 6)
    levels.add(reading(82.4, -65.0, 2, 2.0), 6)
    levels.add(reading(82.4, -61.0, 2, 2.1), 6)
    assert levels.levels == {}


def test_a_note_that_is_not_the_open_string_is_refused_and_reported_once():
    levels = PluckLevels()
    refusal = levels.add(reading(110.0, -20.0, 1, 1.0), 6)  # an A when the low E is asked
    assert refusal is not None and refusal.string == 6 and refusal.note_id == 1
    assert refusal.cents == pytest.approx(1200 * np.log2(110.0 / 82.407), abs=0.01)
    assert levels.add(reading(110.0, -18.0, 1, 1.1), 6) is None
    assert levels.levels == {}


def test_the_open_string_within_60_cents_is_accepted_and_beyond_it_is_refused():
    flat = 82.407 * 2 ** (-59 / 1200)
    very_flat = 82.407 * 2 ** (-61 / 1200)
    levels = PluckLevels()
    assert levels.add(reading(flat, -20.0, 1, 1.0), 6) is None
    assert levels.add(reading(very_flat, -20.0, 2, 2.0), 6) is not None
    assert levels.levels == {6: [-20.0]}


def test_levels_are_kept_per_string_over_the_rounds_and_clear_resets_them():
    levels = PluckLevels()
    note = 0
    for rnd in range(2):
        for string in (6, 5, 4, 3, 2, 1):
            note += 1
            levels.add(reading(OPEN[string], -20.0 - string - rnd, note, note * 2.0), string)
    assert levels.levels[6] == [-26.0, -27.0] and levels.levels[1] == [-21.0, -22.0]
    levels.clear()
    assert levels.levels == {}


# ---- balance ----

def test_balance_gives_the_mean_relative_to_the_six_string_mean_and_the_sample_sd():
    data = {6: [-20.0, -22.0], 5: [-20.0, -20.0], 4: [-21.0, -21.0], 3: [-20.0, -20.0], 2: [-20.0, -20.0],
            1: [-20.0, -20.0]}
    result = balance(data)
    assert result.mean_db == pytest.approx((-21 - 20 - 21 - 20 - 20 - 20) / 6)
    assert result.strings[6].mean_db == pytest.approx(-21.0)
    assert result.strings[6].relative_db == pytest.approx(-21.0 - result.mean_db)
    assert result.strings[6].sd_db == pytest.approx(np.std([-20.0, -22.0], ddof=1))
    assert result.strings[6].rounds == 2
    assert result.strings[5].sd_db == pytest.approx(0.0)


def test_one_round_gives_no_spread():
    assert balance({6: [-20.0], 1: [-20.0]}).strings[6].sd_db is None


def test_a_louder_bass_side_beyond_2_db_advises_lowering_bass_or_raising_treble():
    result = balance({6: [-16.0], 5: [-16.0], 4: [-16.0], 3: [-20.0], 2: [-20.0], 1: [-20.0]})
    assert result.bass_minus_treble_db == pytest.approx(4.0)
    assert result.advice is BalanceAdvice.BASS_LOUDER


def test_a_louder_treble_side_beyond_2_db_advises_the_reverse():
    result = balance({6: [-22.0], 5: [-22.0], 4: [-22.0], 3: [-20.0], 2: [-20.0], 1: [-20.0]})
    assert result.bass_minus_treble_db == pytest.approx(-2.0)
    assert result.advice is BalanceAdvice.OK  # exactly 2 dB is still balanced
    result = balance({6: [-23.0], 5: [-23.0], 4: [-23.0], 3: [-20.0], 2: [-20.0], 1: [-20.0]})
    assert result.advice is BalanceAdvice.TREBLE_LOUDER


def test_a_missing_side_gives_no_difference():
    result = balance({6: [-20.0], 5: [-20.0]})
    assert result.bass_minus_treble_db is None and result.advice is None


def test_position_balance_is_relative_to_the_loudest_and_flags_gaps_over_2_db():
    result = position_balance({"neck": -20.0, "middle": -21.5, "bridge": -23.5})
    assert result.relative_db == {"neck": pytest.approx(0.0), "middle": pytest.approx(-1.5),
                                  "bridge": pytest.approx(-3.5)}
    assert result.flagged == ("bridge",)
    assert position_balance({"neck": -20.0, "bridge": -22.0}).flagged == ()


# ---- magnetic pull ----

def modulated_pluck(f0, depth_cents, rate_hz, dur=2.5):
    """The same kind of pluck as ``audio_signals.pluck`` with a sinusoidal pitch modulation on the phase."""
    t = np.arange(int(dur * SR)) / SR
    bend = 2 ** (depth_cents * np.sin(2 * np.pi * rate_hz * t) / 1200)
    x = np.zeros_like(t)
    for n in range(1, 10):
        phase = 2 * np.pi * np.cumsum(n * f0 * bend) / SR
        x += (1.0 / n) * np.exp(-t * (0.5 + 0.2 * n)) * np.sin(phase)
    return (0.5 * x / np.max(np.abs(x))).astype(np.float32)


def track(samples):
    return feed_in_blocks(PitchTracker(SR), samples)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_clean_pluck_does_not_warn(seed):
    samples, _ = pluck(82.407, dur=2.5, seed=seed)
    result = magnetic_pull(track(samples))
    assert result.peak_to_peak_cents < MAGNETIC_PULL_WARN_CENTS
    assert result.warn is False


@pytest.mark.parametrize("f0", [82.407, 110.0])
def test_a_4_hz_modulation_of_3_cents_warns(f0):
    result = magnetic_pull(track(modulated_pluck(f0, 3.0, 4.0)))
    assert result.peak_to_peak_cents > MAGNETIC_PULL_WARN_CENTS
    assert result.warn is True


def test_the_threshold_is_4_cents():
    assert MAGNETIC_PULL_WARN_CENTS == 4.0


def test_the_first_0_35_seconds_and_a_linear_drift_are_ignored():
    # attack wobble in the first 0.35 s plus a steady drift of 2 cents/s over a clean note: no warning
    readings = [PitchReading(82.4, "E", 2, (15.0 if i * 0.02 < 0.35 else 0.0) + 2.0 * i * 0.02, False, -20.0, False,
                             1, i * 0.02) for i in range(120)]
    result = magnetic_pull(readings)
    assert result.peak_to_peak_cents == pytest.approx(0.0, abs=1e-6)
    assert result.warn is False


def test_a_single_odd_reading_is_removed_by_the_median_smoothing():
    cents = [0.0] * 120
    cents[60] = 30.0
    readings = [PitchReading(82.4, "E", 2, c, False, -20.0, False, 1, i * 0.02) for i, c in enumerate(cents)]
    assert magnetic_pull(readings).warn is False


def test_too_few_readings_give_no_verdict():
    result = magnetic_pull([reading(82.4, -20.0, 1, 0.0)])
    assert result.enough_data is False and result.warn is False and result.peak_to_peak_cents == 0.0
