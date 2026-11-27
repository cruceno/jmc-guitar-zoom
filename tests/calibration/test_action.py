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
