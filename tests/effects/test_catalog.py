import shutil
from pathlib import Path

import pytest

from jmc_guitar_zoom.effects.catalog import (
    a1four_effect_ids,
    load_catalog,
    load_zd2,
)

from fixture_files import EFFECTS as FIX  # noqa: E402



def ranges(info):
    return [(p.name, p.max, p.default) for p in info.params]


def test_comp_metadata_and_params():
    e = load_zd2(FIX / "COMP.ZD2")
    assert (e.name, e.group, e.version, e.effect_id) == ("Comp", "DYNAMICS", "1.40", 0x1000010)
    assert e.dsp_load_percent == pytest.approx(13.94 / 2.5, abs=0.01)
    assert "Dyna Comp" in e.description
    assert ranges(e) == [("Sense", 10, 6), ("ATTCK", 1, 0), ("Tone", 10, 6), ("VOL", 100, 80)]
    assert e.params[0].explanation == "Adjusts the sensitivity of the effect."
    assert not e.is_wide and e.dummy_count == 0
    assert e.svg_path is None


def test_wide_amp_hides_dummies():
    e = load_zd2(FIX / "FDDLXR1U.ZD2")
    assert (e.name, e.group, e.version) == ("FD DLXR", "AMP", "1.10")
    assert e.dsp_load_percent == pytest.approx(77.51 / 2.5, abs=0.01)
    assert ranges(e) == [
        ("Input", 1, 0), ("Bass", 90, 33), ("Treble", 90, 55), ("Gain", 90, 50),
        ("VOL", 90, 90), ("Depth", 90, 0), ("Speed", 100, 40),
    ]
    assert e.is_wide and e.dummy_count == 2 and e.slots == 2


def test_geq_name_with_space_and_dummy():
    e = load_zd2(FIX / "GTGEQ71U.ZD2")
    assert e.name == "Gt GEQ 7"
    assert ranges(e)[:7] == [(p.name, 48, 24) for p in e.params[:7]]
    assert ranges(e)[7] == ("VOL", 100, 80)
    assert len(e.params) == 8 and e.is_wide and e.dummy_count == 1


def test_hall_ranges():
    e = load_zd2(FIX / "HALL.ZD2")
    assert e.name == "Hall"
    assert ranges(e)[:4] == [("PreD", 99, 48), ("Decay", 29, 9), ("Mix", 100, 46), ("Tail", 1, 0)]


def test_prme_with_invalid_json_falls_back_to_elf_names():
    e = load_zd2(FIX / "RACKCOMP.ZD2")  # PRME missing or unparseable
    assert len(e.params) == 4
    assert e.params[0].name == "THRSH" and (e.params[0].max, e.params[0].default) == (60, 38)
    assert e.params[0].explanation == ""


def test_guitar_lab_file_svg_lookup_ignores_version_suffix():
    e = load_zd2(FIX / "lib" / "160_COMP_140.zd2", FIX / "lib" / "SVG")
    assert e.svg_path == FIX / "lib" / "SVG" / "160_COMP.svg"
    assert load_zd2(FIX / "lib" / "MDL_12ST_100.zd2", FIX / "lib" / "SVG").svg_path is None


def test_catalog_keys_and_sources():
    cat = load_catalog(("pedal", FIX), ("library", FIX / "lib"))
    assert {0x1000010, 0x400002C, 0x2000054, 0x9000030} <= set(cat)
    assert cat[0x400002C].sources == ["pedal"]
    assert cat[0x400002C].name == "FD DLXR"


def test_duplicate_id_prefers_higher_version_and_records_sources(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(), new.mkdir()
    shutil.copy(FIX / "COMP.ZD2", old / "COMP.ZD2")  # 1.40
    shutil.copy(FIX / "lib" / "160_COMP_140.zd2", new / "160_COMP_140.zd2")
    e_old = load_zd2(old / "COMP.ZD2")
    e_new = load_zd2(new / "160_COMP_140.zd2")
    assert e_old.effect_id != e_new.effect_id  # different effects, no clash
    # same file in both folders: tie keeps first, merges sources
    shutil.copy(FIX / "COMP.ZD2", new / "COMP.zd2")
    cat = load_catalog(("pedal", old), ("library", new))
    assert cat[e_old.effect_id].sources == ["pedal", "library"]
    assert cat[e_old.effect_id].path.parent == old


def test_duplicate_id_higher_version_wins(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    data = bytearray((FIX / "COMP.ZD2").read_bytes())
    shutil.copy(FIX / "COMP.ZD2", a / "COMP.ZD2")
    idx = data.find(b"1.40")
    assert idx >= 0
    data[idx : idx + 4] = b"1.50"
    (b / "COMP_150.zd2").write_bytes(bytes(data))
    cat = load_catalog(("pedal", a), ("library", b))
    (info,) = cat.values()
    assert info.version == "1.50" and info.filename == "COMP_150.zd2"
    assert info.sources == ["pedal", "library"]


def test_a1four_ids_from_lst_with_trailing_garbage():
    ids = a1four_effect_ids(FIX / "AllZDL7_2.lst")
    assert {0x1000010, 0x400002C, 0x2000054, 0x9000030} <= ids  # unpadded and padded forms
    assert 0x04080021 not in ids  # belongs to model G5n only


@pytest.mark.parametrize("filename,stem", [
    ("160_COMP_140.zd2", "160_COMP"),  # Guitar Lab cache name: NAME_VVV.zd2
    ("MDL_314_100.zd2", "MDL_314"),
    ("MDL_314.ZD2", "MDL_314"),  # a pedal name keeps the digits that end it
    ("COMP.ZD2", "COMP"),
])
def test_effect_stem_only_strips_guitar_lab_version_suffixes(filename, stem):
    from jmc_guitar_zoom.effects.catalog import svg_stem

    assert svg_stem(filename) == stem
