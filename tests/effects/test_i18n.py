import json
from pathlib import Path

import pytest

from jmc_guitar_zoom.effects import i18n
from jmc_guitar_zoom.effects.catalog import EffectInfo, ParamInfo, load_zd2

from fixture_files import EFFECTS as FIX  # noqa: E402

DATA = Path(i18n.__file__).with_name("descriptions_es.json")


def test_known_translation():
    assert i18n.to_spanish("Adjusts the volume.") == "Ajusta el volumen."


def test_unknown_text_falls_back_to_english():
    assert i18n.to_spanish("Totally unknown sentence.") == "Totally unknown sentence."


def test_whitespace_is_stripped_before_lookup():
    assert i18n.to_spanish("  Adjusts the volume.\n") == "Ajusta el volumen."


def test_empty_string():
    assert i18n.to_spanish("") == ""


def test_param_explanation_from_fixture_effect():
    e = load_zd2(FIX / "COMP.ZD2")
    assert e.params[0].explanation == "Adjusts the sensitivity of the effect."
    assert i18n.param_explanation(e.params[0]) == "Ajusta la sensibilidad del efecto."


def test_effect_description_from_fixture_effect_uses_extended_text():
    e = load_zd2(FIX / "COMP.ZD2")
    text = i18n.effect_description(e)
    assert text != e.description
    assert text == i18n._load()["effects"]["0x%08x" % e.effect_id]
    assert len(text) > len(i18n.to_spanish(e.description))


def _info(effect_id, description):
    return EffectInfo(effect_id=effect_id, filename="X.zd2", name="X", group="G", version="1.00",
                      dsp_load_percent=0.0, description=description)


def test_lookup_order_extended_then_translation_then_english():
    extended = _info(0x01000010, "Adjusts the volume.")
    assert i18n.effect_description(extended) == i18n._load()["effects"]["0x01000010"]
    translated = _info(0x7FFFFFFF, "Adjusts the volume.")
    assert i18n.effect_description(translated) == "Ajusta el volumen."
    unknown = _info(0x7FFFFFFF, "Something never translated.")
    assert i18n.effect_description(unknown) == "Something never translated."


def test_param_explanation_fallback():
    assert i18n.param_explanation(ParamInfo("X", "Never seen text.", 1, 0)) == "Never seen text."
    assert i18n.param_explanation(ParamInfo("X", "", 1, 0)) == ""


def test_data_file_is_valid_with_non_empty_strings():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    assert set(data) == {"effects", "texts"}
    for section in data.values():
        assert section
        for key, value in section.items():
            assert isinstance(key, str) and key.strip()
            assert isinstance(value, str) and value.strip()
    assert all(k.startswith("0x") and int(k, 16) >= 0 for k in data["effects"])
    assert all(k == k.strip() for k in data["texts"])
