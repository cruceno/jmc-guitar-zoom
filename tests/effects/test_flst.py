"""FLST_SEQ.ZT2 edits, checked against a real Guitar Lab install of 12Strings on an A1 FOUR."""

from pathlib import Path

import pytest

from zoomstudio.effects import flst

FIXTURES = Path(__file__).parent / "fixtures" / "flst"
BEFORE = (FIXTURES / "before-12st.ZT2").read_bytes()  # 12Strings not installed
AFTER = (FIXTURES / "after-12st.ZT2").read_bytes()  # same pedal after Guitar Lab installed it


def test_install_flag_reproduces_guitar_lab_byte_for_byte():
    assert flst.set_installed(BEFORE, "MDL_12ST.ZD2", True) == AFTER


def test_clearing_the_flag_restores_the_original_list():
    assert flst.set_installed(AFTER, "MDL_12ST.ZD2", False) == BEFORE


def test_setting_the_current_value_changes_nothing():
    assert flst.set_installed(AFTER, "MDL_12ST.ZD2", True) == AFTER


def test_is_installed_reads_the_first_section_only():
    # the second section lists MDL_12ST with its flag already set before the install
    assert flst.is_installed(BEFORE, "MDL_12ST.ZD2") is False
    assert flst.is_installed(AFTER, "MDL_12ST.ZD2") is True
    assert flst.is_installed(BEFORE, "BYPASS.ZD2") is True


def test_installed_names_lists_first_section_flags():
    names = flst.installed_names(AFTER)
    assert "MDL_12ST.ZD2" in names and "MDL_12ST.ZD2" not in flst.installed_names(BEFORE)
    assert len(flst.installed_names(AFTER)) == len(flst.installed_names(BEFORE)) + 1


def test_unknown_effect_is_rejected():
    with pytest.raises(flst.FlstError):
        flst.set_installed(BEFORE, "NOPE.ZD2", True)


def test_unrecognised_layout_is_rejected():
    with pytest.raises(flst.FlstError):
        flst.set_installed(b"\x00" * 100, "MDL_12ST.ZD2", True)


@pytest.mark.parametrize("filename,expected", [
    ("MDL_12ST_100.zd2", "MDL_12ST.ZD2"),
    ("MDL_12ST.ZD2", "MDL_12ST.ZD2"),
    ("B_OCTAVE_140.zd2", "B_OCTAVE.ZD2"),
    # a pedal name that ends in digits is not a Guitar Lab version suffix (314ce lost its digits)
    ("MDL_314.ZD2", "MDL_314.ZD2"),
    ("MDL_314_100.zd2", "MDL_314.ZD2"),
])
def test_pedal_filename_from_catalog_filename(filename, expected):
    assert flst.pedal_filename(filename) == expected


def test_every_flag_change_keeps_the_length_and_touches_one_byte():
    # S5: FLST_SEQ.ZT2 is edited in place, never rebuilt (zoomzt2's rebuild truncates it)
    for name in flst.installed_names(AFTER):
        for value in (False, True):
            changed = flst.set_installed(AFTER, name, value)
            assert len(changed) == len(AFTER)
            assert sum(a != b for a, b in zip(changed, AFTER)) <= 1
