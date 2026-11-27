import dataclasses

import pytest

from jmc_guitar_zoom.calibration import (CUSTOM, FENDER_STYLE, GIBSON_STYLE, HUMBUCKER, P90, PRESETS, SINGLE_COIL,
                                         GuitarPreset)


def test_the_fender_style_preset_holds_the_typical_starting_values():
    p = FENDER_STYLE
    assert p.name == "Estilo Fender (simple)"
    assert (p.relief_mm, p.action_bass_mm, p.action_treble_mm, p.radius_in) == (0.25, 1.8, 1.6, 9.5)
    assert p.bridge_span_mm == 52
    assert p.pickups == (("neck", SINGLE_COIL), ("middle", SINGLE_COIL), ("bridge", SINGLE_COIL))


def test_the_gibson_style_preset_holds_the_typical_starting_values():
    p = GIBSON_STYLE
    assert p.name == "Estilo Gibson (humbucker)"
    assert (p.relief_mm, p.action_bass_mm, p.action_treble_mm, p.radius_in) == (0.30, 2.0, 1.5, 12)
    assert p.pickups == (("neck", HUMBUCKER), ("bridge", HUMBUCKER))


def test_every_preset_carries_the_pickup_targets_of_the_three_types():
    expected = {SINGLE_COIL: (3.2, 2.4), HUMBUCKER: (2.4, 1.6), P90: (3.2, 2.4)}
    for preset in (FENDER_STYLE, GIBSON_STYLE, CUSTOM):
        for kind, (bass, treble) in expected.items():
            target = preset.target_for_type(kind)
            assert (target.bass_mm, target.treble_mm) == (bass, treble)
            assert (target.bass_string, target.treble_string) == (6, 1)  # fretted at the last fret


def test_a_position_resolves_to_its_pickup_type_and_target():
    assert FENDER_STYLE.pickup_type("middle") == SINGLE_COIL
    assert GIBSON_STYLE.target_for("bridge").bass_mm == 2.4
    with pytest.raises(ValueError):
        GIBSON_STYLE.pickup_type("middle")


def test_the_custom_preset_is_an_editable_copy_and_the_list_has_the_three_in_order():
    assert CUSTOM.name == "Personalizado"
    assert dataclasses.replace(CUSTOM, name=FENDER_STYLE.name) == FENDER_STYLE
    assert [p.name for p in PRESETS] == ["Estilo Fender (simple)", "Estilo Gibson (humbucker)", "Personalizado"]


def test_with_changes_returns_a_new_preset_and_leaves_the_original_alone():
    edited = FENDER_STYLE.with_changes(relief_mm=0.20, radius_in=7.25)
    assert (edited.relief_mm, edited.radius_in) == (0.20, 7.25)
    assert edited.action_bass_mm == 1.8
    assert FENDER_STYLE.relief_mm == 0.25 and FENDER_STYLE.radius_in == 9.5
    assert isinstance(edited, GuitarPreset)


def test_presets_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        FENDER_STYLE.relief_mm = 1.0  # type: ignore[misc]
