import pytest

from jmc_guitar_zoom.calibration import ReliefMove, relief_advice


def test_a_measure_inside_the_tolerance_is_ok_and_asks_for_no_turn():
    advice = relief_advice(0.27, 0.25)
    assert advice.move is ReliefMove.OK
    assert advice.error_mm == pytest.approx(0.02)
    assert advice.turn_fraction == 0


def test_the_tolerance_edges_are_still_ok():
    assert relief_advice(0.30, 0.25).move is ReliefMove.OK
    assert relief_advice(0.20, 0.25).move is ReliefMove.OK
    assert relief_advice(0.305, 0.25).move is ReliefMove.TIGHTEN
    assert relief_advice(0.195, 0.25).move is ReliefMove.LOOSEN


def test_too_much_relief_tightens_the_truss_rod_clockwise_by_at_most_an_eighth_of_a_turn():
    advice = relief_advice(0.60, 0.25)
    assert advice.move is ReliefMove.TIGHTEN
    assert advice.error_mm == pytest.approx(0.35)
    assert advice.clockwise is True
    assert advice.turn_fraction == pytest.approx(1 / 8)


def test_too_little_relief_loosens_the_truss_rod_counter_clockwise_by_at_most_an_eighth_of_a_turn():
    advice = relief_advice(0.05, 0.25)
    assert advice.move is ReliefMove.LOOSEN
    assert advice.error_mm == pytest.approx(-0.20)
    assert advice.clockwise is False
    assert advice.turn_fraction == pytest.approx(1 / 8)


def test_a_custom_tolerance_is_honoured():
    assert relief_advice(0.30, 0.25, tolerance_mm=0.02).move is ReliefMove.TIGHTEN
    assert relief_advice(0.30, 0.25, tolerance_mm=0.10).move is ReliefMove.OK


@pytest.mark.parametrize("measured,target", [(-0.1, 0.25), (2.5, 0.25), (0.2, -0.1), (0.2, 3.0), (float("nan"), 0.25)])
def test_negative_or_absurd_values_are_rejected(measured, target):
    with pytest.raises(ValueError):
        relief_advice(measured, target)
