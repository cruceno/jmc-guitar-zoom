import math

import pytest

from jmc_guitar_zoom.calibration import FENDER_STYLE, ActionMove, action_advice, action_targets, saddle_arc


def test_targets_are_interpolated_linearly_between_strings_6_and_1():
    targets = action_targets(FENDER_STYLE)  # 1.8 bass, 1.6 treble
    assert set(targets) == {1, 2, 3, 4, 5, 6}
    assert targets[6] == pytest.approx(1.8) and targets[1] == pytest.approx(1.6)
    assert targets[3] == pytest.approx(1.8 - 0.2 * 3 / 5)
    assert targets[4] == pytest.approx(1.8 - 0.2 * 2 / 5)


def test_a_high_string_is_lowered_with_a_saddle_move_of_twice_the_error():
    advice = action_advice({6: 2.5}, FENDER_STYLE)[6]
    assert advice.move is ActionMove.LOWER
    assert advice.target_mm == pytest.approx(1.8)
    assert advice.error_mm == pytest.approx(0.7)
    assert advice.saddle_mm == pytest.approx(1.4)


def test_a_low_string_is_raised_and_the_saddle_move_is_a_magnitude():
    advice = action_advice({1: 1.1}, FENDER_STYLE)[1]
    assert advice.move is ActionMove.RAISE
    assert advice.error_mm == pytest.approx(-0.5)
    assert advice.saddle_mm == pytest.approx(1.0)


def test_inside_the_tolerance_is_ok_without_a_saddle_move():
    advice = action_advice({6: 1.9, 1: 1.5}, FENDER_STYLE)
    assert advice[6].move is ActionMove.OK and advice[6].saddle_mm == 0
    assert advice[1].move is ActionMove.OK and advice[1].saddle_mm == 0


def test_the_tolerance_edge_is_ok_and_a_custom_tolerance_is_honoured():
    assert action_advice({6: 1.9}, FENDER_STYLE)[6].move is ActionMove.OK
    assert action_advice({6: 1.95}, FENDER_STYLE)[6].move is ActionMove.LOWER
    assert action_advice({6: 1.95}, FENDER_STYLE, tolerance_mm=0.2)[6].move is ActionMove.OK


def test_middle_strings_use_the_interpolated_target_and_unmeasured_strings_are_absent():
    result = action_advice({3: 2.0}, FENDER_STYLE)
    assert set(result) == {3}
    assert result[3].target_mm == pytest.approx(1.68)


@pytest.mark.parametrize("measured", [{7: 1.8}, {0: 1.8}, {3: -1.0}, {3: 12.0}])
def test_invalid_strings_or_values_are_rejected(measured):
    with pytest.raises(ValueError):
        action_advice(measured, FENDER_STYLE)


def sagitta(radius_mm, x):
    return radius_mm - math.sqrt(radius_mm ** 2 - x ** 2)


@pytest.mark.parametrize("radius_in", [7.25, 9.5, 12, 16])
def test_the_saddle_arc_follows_the_sagitta_of_the_fretboard_radius(radius_in):
    r = radius_in * 25.4
    arc = saddle_arc(radius_in, 52)
    assert set(arc) == {1, 2, 3, 4, 5, 6}
    assert arc[6] == pytest.approx(0) and arc[1] == pytest.approx(0)
    for string, x in zip((6, 5, 4, 3, 2, 1), (-26, -15.6, -5.2, 5.2, 15.6, 26)):
        assert arc[string] == pytest.approx(sagitta(r, 26) - sagitta(r, x), abs=1e-9)
    assert arc[3] == pytest.approx(arc[4]) and arc[2] == pytest.approx(arc[5])
    assert arc[3] > arc[2] > 0


def test_the_9_5_inch_arc_rises_about_1_4_mm_between_the_outer_strings_and_the_centre():
    r = 9.5 * 25.4
    assert sagitta(r, 26) == pytest.approx(1.4, abs=0.02)
    assert saddle_arc(9.5, 52)[3] == pytest.approx(1.34, abs=0.02)


def test_a_flatter_radius_gives_a_flatter_arc_and_a_narrower_span_too():
    assert saddle_arc(16, 52)[3] < saddle_arc(7.25, 52)[3]
    assert saddle_arc(9.5, 40)[3] < saddle_arc(9.5, 52)[3]


@pytest.mark.parametrize("radius,span", [(0, 52), (-9.5, 52), (9.5, 0), (9.5, -3)])
def test_the_arc_rejects_non_positive_inputs(radius, span):
    with pytest.raises(ValueError):
        saddle_arc(radius, span)


def test_the_post_move_solves_the_lever_system_for_a_hand_computed_case():
    from jmc_guitar_zoom.calibration import GIBSON_STYLE, two_post_advice
    # P=74, span=52 -> a=11. Errors at the 12th: string 6 +0.5, string 1 -0.3 -> wanted saddle changes -1.0 and +0.6.
    # The posts' lever equations are solved by hand below (Cramer's rule) and cross-checked.
    preset = GIBSON_STYLE.with_changes(action_bass_mm=2.0, action_treble_mm=1.5)
    advice = two_post_advice(2.5, 1.2, preset)
    p, a = 74.0, 11.0
    want6, want1 = -2 * 0.5, -2 * -0.3  # too high -> lower; too low -> raise
    det = ((p - a) ** 2 - a ** 2) / p ** 2
    b = (want6 * (p - a) / p - want1 * a / p) / det
    t = (want1 * (p - a) / p - want6 * a / p) / det
    assert advice.bass_post_mm == pytest.approx(abs(b)) and advice.treble_post_mm == pytest.approx(abs(t))
    # the solution really produces the wanted heights
    assert b * (p - a) / p + t * a / p == pytest.approx(want6)
    assert b * a / p + t * (p - a) / p == pytest.approx(want1)
    assert advice.bass_move is ActionMove.LOWER and advice.treble_move is ActionMove.RAISE


def test_a_post_move_at_twice_the_tolerance_edge_is_ok_and_beyond_it_is_not():
    from jmc_guitar_zoom.calibration import GIBSON_STYLE, two_post_advice
    # equal errors on both strings -> both posts move by 2*error
    ok = two_post_advice(2.1, 1.6, GIBSON_STYLE)  # errors +0.1, +0.1 -> moves 0.2 = 2*tolerance
    assert ok.bass_move is ActionMove.OK and ok.treble_move is ActionMove.OK
    off = two_post_advice(2.15, 1.65, GIBSON_STYLE)
    assert off.bass_move is ActionMove.LOWER and off.treble_move is ActionMove.LOWER
    assert off.bass_post_mm == pytest.approx(0.3)
    low = two_post_advice(1.8, 1.3, GIBSON_STYLE)
    assert low.bass_move is ActionMove.RAISE and low.bass_post_mm == pytest.approx(0.4)
    assert two_post_advice(2.15, 1.65, GIBSON_STYLE, tolerance_mm=0.2).bass_move is ActionMove.OK


def test_the_expected_middle_strings_are_linear_between_the_new_outer_heights():
    from jmc_guitar_zoom.calibration import GIBSON_STYLE, two_post_advice
    advice = two_post_advice(2.5, 1.2, GIBSON_STYLE)
    # after the change strings 6 and 1 sit at their targets (2.0 and 1.5): the posts fix the outer strings
    assert advice.expected_mm[6] == pytest.approx(2.0) and advice.expected_mm[1] == pytest.approx(1.5)
    assert advice.expected_mm[3] == pytest.approx(2.0 - 0.5 * 3 / 5)
    assert set(advice.expected_mm) == {1, 2, 3, 4, 5, 6}


def test_a_measured_middle_string_reports_its_difference_from_the_expectation():
    from jmc_guitar_zoom.calibration import GIBSON_STYLE, two_post_advice
    advice = two_post_advice(2.5, 1.2, GIBSON_STYLE, middle={3: 2.0})
    assert advice.middle_mismatch_mm[3] == pytest.approx(2.0 - (2.0 - 0.5 * 3 / 5))
    assert two_post_advice(2.5, 1.2, GIBSON_STYLE).middle_mismatch_mm == {}


def test_the_saddle_height_path_still_gives_todays_advice_for_the_fender_preset():
    advice = action_advice({6: 2.5}, FENDER_STYLE)[6]
    assert (advice.move, advice.saddle_mm) == (ActionMove.LOWER, pytest.approx(1.4))
