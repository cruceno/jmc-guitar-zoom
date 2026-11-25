import json
from types import SimpleNamespace

from jmc_guitar_zoom.effects import models
from jmc_guitar_zoom.effects.catalog import a1four_effect_ids
from jmc_guitar_zoom.effects.models import A1_FOUR, PedalModel, load_models, model_id_from_identity

LST = {"models": [
    {"modelId": "0x6E000000", "modelName": "G5n", "editor": True, "effects": [{"type": "0x1000010"}, {"type": "0x1000020"}]},
    {"modelId": "0x6E001100", "modelName": "A1 FOUR", "editor": True, "effects": [{"type": "0x1000010"}]},
    {"modelId": "0x6E00FF00", "modelName": "UNSEL", "editor": False, "effects": []},
]}


def write(tmp_path, garbage=b"\x00\x00trailing {garbage"):
    path = tmp_path / "AllZDL7_2.lst"
    path.write_bytes(json.dumps(LST).encode() + garbage)
    return path


def test_models_with_effects_are_parsed_and_empty_ones_are_ignored(tmp_path):
    found = load_models(write(tmp_path))
    assert set(found) == {0x6E000000, 0x6E001100}
    assert found[0x6E001100] == PedalModel(0x6E001100, "A1 FOUR", frozenset({0x1000010}))
    assert found[0x6E000000].effect_ids == {0x1000010, 0x1000020}


def test_the_real_fixture_list_parses_and_matches_the_a1_helper():
    from pathlib import Path

    from fixture_files import UI

    path = UI / "AllZDL7_2.lst"
    found = load_models(path)
    assert found[A1_FOUR].name == "A1 FOUR" and found[A1_FOUR].effect_ids == a1four_effect_ids(path)


def test_the_model_id_comes_from_the_identity_member_byte():
    assert model_id_from_identity(SimpleNamespace(model=0x6E, member=0x11)) == 0x6E001100  # A1 FOUR
    assert model_id_from_identity(SimpleNamespace(model=0x6E, member=0x0C)) == 0x6E000C00  # G1 FOUR
    assert model_id_from_identity(SimpleNamespace(model=0x6E, member=0x00)) == 0x6E000000  # G5n


def test_only_the_a1_four_is_supported_today():
    assert models.SUPPORTED_MODELS == {0x6E001100}


def test_unusable_entries_are_skipped_not_fatal(tmp_path):
    # verifier B1: a list saved from the channel must never make the app's reader raise
    doc = {"models": [
        "not a dict",
        {"modelId": "zz", "modelName": "Bad id", "effects": [{"type": "0x01000010"}]},
        {"modelId": "0x6E000C00", "modelName": "G1 FOUR", "effects": None},
        {"modelId": "0x6E001100", "modelName": "A1 FOUR",
         "effects": [{"type": "0x01000010"}, {"type": "zz"}, {"fileName": "x.zip"}, "junk"]},
    ]}
    path = tmp_path / "AllZDL7_2.lst"
    path.write_bytes(json.dumps(doc).encode() + b"\x00garbage")
    found = load_models(path)
    assert set(found) == {0x6E001100} and found[0x6E001100].effect_ids == {0x01000010}


def test_a_list_without_a_models_array_gives_no_models(tmp_path):
    for doc in ({"models": None}, {"models": 5}, [1, 2]):
        path = tmp_path / "l.lst"
        path.write_text(json.dumps(doc))
        assert load_models(path) == {}
