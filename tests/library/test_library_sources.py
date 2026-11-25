"""The app's own library is a catalog source that wins by version and feeds the model registry."""
from pathlib import Path

from updater_support import A1, COMP, effect, effects_lst

from zoomstudio import __main__ as entry
from zoomstudio.effects import flst
from zoomstudio.effects.catalog import load_catalog, load_zd2
from zoomstudio.effects.models import load_models

FIX = Path(__file__).parents[1] / "effects" / "fixtures"


def newer_comp(version=b"1.50") -> bytes:
    return COMP[3].read_bytes().replace(b"1.40", version, 1)


def workspace(tmp_path, with_library=True, library_files=True):
    gl = tmp_path / "guitarlab" / "GL"
    (gl / "cache").mkdir(parents=True)
    (gl / "COMP_140.zd2").write_bytes(COMP[3].read_bytes())
    (gl / "cache" / "AllZDL7_2.lst").write_bytes(effects_lst({A1: [effect(COMP)]}))
    lib = entry.library_dir(tmp_path)
    if with_library:
        lib.mkdir(parents=True)
        if library_files:
            (lib / "COMP_150.zd2").write_bytes(newer_comp())
    return gl, lib


def test_the_library_folder_is_the_apps_own_under_the_workspace(tmp_path):
    assert entry.library_dir(tmp_path) == tmp_path / "library" / "effects"


def test_the_library_comes_before_guitar_lab(tmp_path):
    gl, lib = workspace(tmp_path)
    assert entry.default_catalogs(tmp_path) == [("Biblioteca", lib), ("Guitar Lab", gl)]


def test_the_library_goes_after_the_pedal_dump_and_before_guitar_lab(tmp_path):
    gl, lib = workspace(tmp_path)
    (tmp_path / "patches" / "pedal-files-20260101").mkdir(parents=True)
    labels = [label for label, _ in entry.default_catalogs(tmp_path)]
    assert labels == ["pedal", "Biblioteca", "Guitar Lab"]


def test_an_empty_or_missing_library_changes_nothing(tmp_path):
    gl, _ = workspace(tmp_path, with_library=False)
    assert entry.default_catalogs(tmp_path) == [("Guitar Lab", gl)]
    gl2, _ = workspace(tmp_path / "b", library_files=False)
    assert entry.default_catalogs(tmp_path / "b") == [("Guitar Lab", gl2)]


def test_the_newest_version_wins_whichever_folder_it_came_from(tmp_path):
    workspace(tmp_path)
    catalog = load_catalog(*entry.default_catalogs(tmp_path))
    assert catalog[0x1000010].version == "1.50"
    assert catalog[0x1000010].path.parent == entry.library_dir(tmp_path)
    assert sorted(catalog[0x1000010].sources) == ["Biblioteca", "Guitar Lab"]


def test_guitar_lab_still_wins_when_it_holds_the_newer_version(tmp_path):
    gl, lib = workspace(tmp_path)
    (lib / "COMP_150.zd2").unlink()
    (lib / "COMP_130.zd2").write_bytes(newer_comp(b"1.30"))
    assert load_catalog(*entry.default_catalogs(tmp_path))[0x1000010].version == "1.40"


def test_the_pedal_filename_is_the_same_for_every_version():
    assert flst.pedal_filename("COMP_150.zd2") == flst.pedal_filename("COMP_140.zd2") == "COMP.ZD2"


def test_the_library_list_is_preferred_when_it_exists(tmp_path):
    gl, lib = workspace(tmp_path)
    catalogs = entry.default_catalogs(tmp_path)
    assert entry.find_a1_list(catalogs, lib) == gl / "cache" / "AllZDL7_2.lst"  # nothing downloaded yet
    (lib / "AllZDL7_2.lst").write_bytes(effects_lst({A1: [effect(COMP)]}))
    assert entry.find_a1_list(catalogs, lib) == lib / "AllZDL7_2.lst"
    assert 0x6E001100 in load_models(entry.find_a1_list(catalogs, lib))


def test_find_a1_list_keeps_its_old_behaviour_without_a_library(tmp_path):
    assert entry.find_a1_list([("x", tmp_path)]) is None
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "AllZDL7_2.lst").write_bytes(b"{}")
    assert entry.find_a1_list([("x", tmp_path)]) == tmp_path / "cache" / "AllZDL7_2.lst"
    assert entry.find_a1_list([("x", tmp_path)], tmp_path / "nope") == tmp_path / "cache" / "AllZDL7_2.lst"


def test_a_bumped_copy_is_a_valid_newer_effect(tmp_path):
    path = tmp_path / "c.zd2"
    path.write_bytes(newer_comp())
    assert load_zd2(path).version == "1.50"
