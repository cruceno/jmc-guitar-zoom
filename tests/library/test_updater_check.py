import dataclasses

import pytest
from updater_support import A1, COMP, G5N, GARBAGE, GEQ, HALL, FakeFetcher, effect, effects_lst, standard_routes, versions_lst

from jmc_guitar_zoom.effects.catalog import load_zd2
from jmc_guitar_zoom.effects.models import load_models
from jmc_guitar_zoom.library import updater
from jmc_guitar_zoom.library.updater import LibraryUpdater


def local_of(*specs_versions):
    """A local catalog of the given (spec, version) pairs, built from the real fixture files."""
    out = {}
    for spec, version in specs_versions:
        out[int(spec[0], 16)] = dataclasses.replace(load_zd2(spec[3]), version=version)
    return out


def make(tmp_path, routes=None):
    fetcher = FakeFetcher(standard_routes() if routes is None else routes)
    return LibraryUpdater(tmp_path / "lib", fetcher=fetcher), fetcher


def test_the_lists_are_read_even_with_trailing_garbage_and_a_nul(tmp_path):
    up, _ = make(tmp_path)
    result = up.check(model_id=0x6E001100, local={})
    assert {u.effect_id for u in result.new} == {0x1000010, 0x9000030, 0x2000054}
    assert updater.parse_effect_list(effects_lst({A1: [effect(COMP)]}, b"\x00\x00{garbage"))[0x6E001100][0].file_name == "COMP.zip"


def test_new_updated_and_current_are_told_apart(tmp_path):
    up, _ = make(tmp_path)
    local = local_of((COMP, "1.40"), (HALL, "1.30"))  # COMP current, HALL older, GEQ unknown
    result = up.check(model_id=0x6E001100, local=local)
    assert [(u.effect_id, u.kind, u.version, u.local_version) for u in result.new] == [(0x2000054, "new", "1.20", None)]
    assert [(u.effect_id, u.kind, u.version, u.local_version) for u in result.updated] == [(0x9000030, "updated", "1.50", "1.30")]
    assert [u.effect_id for u in result.current] == [0x1000010]
    assert result.updated[0].name == load_zd2(HALL[3]).name  # the local name when known
    assert result.updated[0].group == "REVERB"


def test_a_local_version_equal_or_newer_is_up_to_date(tmp_path):
    up, _ = make(tmp_path)
    local = local_of((COMP, "1.90"), (HALL, "1.50"), (GEQ, "1.20"))
    result = up.check(model_id=0x6E001100, local=local)
    assert result.new == [] and result.updated == [] and len(result.current) == 3


def test_versions_compare_as_numbers_not_text(tmp_path):
    up, _ = make(tmp_path, standard_routes({A1: [effect((COMP[0], COMP[1], "1.10"))]}))
    assert len(up.check(model_id=0x6E001100, local=local_of((COMP, "1.9"))).updated) == 1  # (1, 10) > (1, 9)
    assert up.check(model_id=0x6E001100, local=local_of((COMP, "1.10"))).updated == []


def test_one_model_only_by_default_and_every_model_on_request(tmp_path):
    models = {A1: [effect(COMP)], G5N: [effect(COMP), effect(HALL)]}
    up, _ = make(tmp_path, standard_routes(models))
    assert {u.effect_id for u in up.check(model_id=0x6E001100, local={}).new} == {0x1000010}
    everything = up.check(all_models=True, local={})
    assert sorted(u.effect_id for u in everything.new) == [0x1000010, 0x9000030]  # COMP once, not twice


def test_an_unknown_model_has_no_effects_and_no_error(tmp_path):
    up, _ = make(tmp_path)
    assert up.check(model_id=0x6E00AB00, local={}).new == []


def test_the_firmware_is_compared_with_the_connected_pedal(tmp_path):
    up, _ = make(tmp_path)
    newer = up.check(model_id=0x6E001100, firmware="1.01", local={}).firmware
    assert (newer.model_id, newer.remote, newer.current, newer.newer) == (0x6E001100, "1.02", "1.01", True)
    same = up.check(model_id=0x6E001100, firmware="1.02", local={}).firmware
    assert same.newer is False
    unknown = up.check(model_id=0x6E001100, firmware=None, local={}).firmware
    assert unknown.newer is False and unknown.current is None
    assert up.check(model_id=0x6E00AB00, firmware="1.01", local={}).firmware is None  # the channel does not list it


def test_firmware_versions_compare_as_numbers(tmp_path):
    up, _ = make(tmp_path, standard_routes(versions={A1: "1.10"}))
    assert up.check(model_id=0x6E001100, firmware="1.9", local={}).firmware.newer is True


def test_entries_with_a_bad_file_name_are_skipped_not_fatal(tmp_path):
    bad = [{"type": "0x01000010", "fileName": "../evil.zip", "version": "1.00"},
           {"type": "0x01000011", "fileName": "a/b.zip", "version": "1.00"},
           {"type": "0x01000012", "fileName": "x.exe", "version": "1.00"},
           {"type": "zz", "fileName": "OK.zip", "version": "1.00"}, effect(HALL)]
    up, _ = make(tmp_path, standard_routes({A1: bad}))
    result = up.check(model_id=0x6E001100, local={})
    assert [u.effect_id for u in result.new] == [0x9000030] and result.skipped == 4


def test_only_the_two_lists_are_requested_and_both_under_the_channel(tmp_path):
    up, fetcher = make(tmp_path)
    up.check(model_id=0x6E001100, local={})
    assert sorted(fetcher.urls) == sorted([updater.EFFECTS_LIST_URL, updater.VERSIONS_LIST_URL])
    assert all(u.startswith("https://www.zoom.co.jp/archive/GUITAR_LAB/") for u in fetcher.urls)


def test_a_failed_fetch_raises_one_clear_error_and_saves_nothing(tmp_path):
    routes = standard_routes()
    routes[updater.VERSIONS_LIST_URL] = updater.FetchError("sin red")
    up, _ = make(tmp_path, routes)
    with pytest.raises(updater.UpdateError):
        up.check(model_id=0x6E001100, local={})
    assert not (tmp_path / "lib" / "AllZDL7_2.lst").exists()


def test_a_list_that_does_not_parse_is_an_error_and_is_not_saved(tmp_path):
    routes = standard_routes()
    routes[updater.EFFECTS_LIST_URL] = b"<html>oops</html>"
    up, _ = make(tmp_path, routes)
    with pytest.raises(updater.UpdateError):
        up.check(model_id=0x6E001100, local={})
    assert list((tmp_path / "lib").glob("*.lst")) == []


def test_good_lists_are_saved_into_the_library_after_they_parse(tmp_path):
    up, _ = make(tmp_path)
    up.check(model_id=0x6E001100, local={})
    saved = tmp_path / "lib" / "AllZDL7_2.lst"
    assert saved.read_bytes() == standard_routes()[updater.EFFECTS_LIST_URL]
    assert (tmp_path / "lib" / "ModelVersion7_2.lst").is_file()
    assert 0x6E001100 in load_models(saved)  # the app's own reader takes the saved copy
    assert [p.name for p in (tmp_path / "lib").iterdir() if p.suffix == ".part"] == []


def test_the_default_local_state_is_read_from_the_library_and_extra_folders(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "COMP_140.zd2").write_bytes(COMP[3].read_bytes())
    gl = tmp_path / "gl"
    gl.mkdir()
    (gl / "HALL_150.zd2").write_bytes(HALL[3].read_bytes())
    up = LibraryUpdater(lib, fetcher=FakeFetcher(standard_routes()), extra_dirs=[gl])
    result = up.check(model_id=0x6E001100)
    assert [u.effect_id for u in result.new] == [0x2000054]
    assert sorted(u.effect_id for u in result.current) == [0x1000010, 0x9000030]


def test_every_models_firmware_is_listed_so_a_later_connection_can_compare(tmp_path):
    up, _ = make(tmp_path, standard_routes(versions={A1: "1.02", G5N: "3.00"}))
    assert up.check(model_id=0x6E001100, local={}).firmware_versions == {0x6E001100: "1.02", 0x6E000000: "3.00"}


def test_the_update_flag_of_the_channel_makes_the_firmware_an_update_even_at_the_same_version(tmp_path):
    flagged, _ = make(tmp_path, standard_routes(versions={A1: ("1.01", True)}))
    status = flagged.check(model_id=0x6E001100, firmware="1.01", local={}).firmware
    assert (status.remote, status.newer, status.update) == ("1.01", True, True)


def test_the_same_version_without_the_update_flag_is_not_an_update(tmp_path):
    same, _ = make(tmp_path, standard_routes(versions={A1: ("1.01", False)}))
    status = same.check(model_id=0x6E001100, firmware="1.01", local={}).firmware
    assert (status.newer, status.update) == (False, False)
    assert same.check(model_id=0x6E001100, firmware="1.01", local={}).firmware_updates == set()


def test_a_saved_list_always_loads_even_with_malformed_entries(tmp_path):
    # verifier B1: the updater saved a list that the startup reader could not load
    bad = {"models": [{"modelId": "0x6E001100", "modelName": "A1 FOUR",
                       "effects": [effect(COMP), {"type": "zz", "fileName": "a.zip", "version": "1.00"}]}]}
    routes = standard_routes()
    routes[updater.EFFECTS_LIST_URL] = __import__("json").dumps(bad).encode() + GARBAGE
    up, _ = make(tmp_path, routes)
    up.check(model_id=0x6E001100, local={})
    assert 0x6E001100 in load_models(tmp_path / "lib" / "AllZDL7_2.lst")


def test_a_list_with_no_usable_model_is_an_error_and_is_not_saved(tmp_path):
    # verifier A4: an empty registry would leave the editor catalog unfiltered
    routes = standard_routes()
    routes[updater.EFFECTS_LIST_URL] = b'{"models": []}' + GARBAGE
    up, _ = make(tmp_path, routes)
    with pytest.raises(updater.UpdateError):
        up.check(model_id=0x6E001100, local={})
    assert list((tmp_path / "lib").glob("*.lst")) == []


@pytest.mark.parametrize("url,ok", [
    ("https://www.zoom.co.jp/archive/GUITAR_LAB/ZDLF3/COMP.zip", True),
    ("https://www.zoom.co.jp/archive/GUITAR_LAB/../../other", False),  # verifier A2
    ("https://www.zoom.co.jp/archive/GUITAR_LAB/%2e%2e/%2e%2e/other", False),
    ("https://www.zoom.co.jp/archive/GUITAR_LAB/ZDLF3/./../../x", False),
    ("https://www.zoom.co.jp/archive/GUITAR_LAB@evil.com/x", False),
    ("http://www.zoom.co.jp/archive/GUITAR_LAB/x", False),
    ("https://www.zoom.co.jp.evil.com/archive/GUITAR_LAB/x", False),
])
def test_only_normalised_paths_inside_the_channel_are_allowed(url, ok):
    assert updater.within_channel(url) is ok


def test_a_version_with_non_ascii_digits_is_skipped():
    # verifier A3: \d accepted Arabic-Indic digits
    lst = effects_lst({A1: [effect(COMP), {"type": "0x09000030", "fileName": "HALL.zip", "version": "١.٢٣"}]})
    parsed = updater.parse_effect_list(lst)
    assert [e.file_name for e in parsed[0x6E001100]] == ["COMP.zip"]
