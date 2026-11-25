import sys
import tomllib
from pathlib import Path

import jmc_guitar_zoom
from jmc_guitar_zoom import paths
from jmc_guitar_zoom.__main__ import autosave_dir, default_catalogs, library_dir, workspace_root
from jmc_guitar_zoom.patches import bank


def _frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "data")
    return tmp_path / "data"


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text())["project"]["version"] == jmc_guitar_zoom.__version__


def test_source_mode_keeps_the_workspace_layout():
    assert not paths.is_frozen()
    root = workspace_root()
    assert paths.data_root() == root == Path(jmc_guitar_zoom.__file__).resolve().parents[2]
    assert library_dir() == root / "library" / "effects"
    assert autosave_dir() == root / "patches" / "autosave"
    assert bank.default_dir() == root / "patches" / "bank"
    assert library_dir(Path("/w")) == Path("/w/library/effects")


def test_frozen_moves_every_location_to_the_user_data_folder(monkeypatch, tmp_path):
    data = _frozen(monkeypatch, tmp_path)
    assert paths.is_frozen()
    assert paths.data_root() == data
    assert library_dir() == data / "library" / "effects"
    assert autosave_dir() == data / "patches" / "autosave"
    assert bank.default_dir() == data / "patches" / "bank"
    assert workspace_root() == paths.source_root()  # the source layout helper itself does not move


def test_frozen_default_catalogs_read_the_pedal_files_from_the_data_folder(monkeypatch, tmp_path):
    data = _frozen(monkeypatch, tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("APPDATA", raising=False)
    (data / "patches" / "pedal-files-1").mkdir(parents=True)
    assert default_catalogs() == [("pedal", data / "patches" / "pedal-files-1")]


def test_user_data_dir_uses_the_app_name_before_any_qapplication():
    from PySide6.QtCore import QStandardPaths

    QStandardPaths.setTestModeEnabled(True)
    try:
        folder = paths.user_data_dir()
        assert folder.name == "JMC Guitar Zoom" and folder.parent.name != "JMC Guitar Zoom"
    finally:
        QStandardPaths.setTestModeEnabled(False)


def _zd2(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "A.ZD2").write_bytes(b"x")
    return folder


def _isolate(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("APPDATA", raising=False)
    return home


def test_guitarlab_none_when_nothing_exists(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert paths.guitarlab_dir(tmp_path / "nowhere") is None


def test_guitarlab_source_folder_wins_then_appdata_wine_bottles(monkeypatch, tmp_path):
    home = _isolate(monkeypatch, tmp_path)
    bottles = _zd2(home / ".var/app/com.usebottles.bottles/data/bottles/bottles/b1/drive_c/users/u/AppData/Roaming/GL")
    assert paths.guitarlab_dir(tmp_path / "root") == bottles
    wine = _zd2(home / ".wine/drive_c/users/u/AppData/Roaming/GL")
    assert paths.guitarlab_dir(tmp_path / "root") == wine
    appdata = _zd2(tmp_path / "Roaming" / "GL")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert paths.guitarlab_dir(tmp_path / "root") == appdata
    local = tmp_path / "root" / "guitarlab" / "GL"
    local.mkdir(parents=True)
    assert paths.guitarlab_dir(tmp_path / "root") == local


def test_guitarlab_skips_folders_without_zd2_and_frozen_ignores_the_source_folder(monkeypatch, tmp_path):
    home = _isolate(monkeypatch, tmp_path)
    (home / ".wine/drive_c/users/u/AppData/Roaming/GL").mkdir(parents=True)
    bottles = _zd2(home / ".var/app/com.usebottles.bottles/data/bottles/bottles/b1/drive_c/users/u/AppData/Roaming/GL")
    (tmp_path / "root" / "guitarlab" / "GL").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.guitarlab_dir(tmp_path / "root") == bottles


def test_default_catalogs_with_a_root_keep_the_source_layout(tmp_path):
    (tmp_path / "patches" / "pedal-files-1").mkdir(parents=True)
    (tmp_path / "guitarlab" / "GL").mkdir(parents=True)
    assert default_catalogs(tmp_path) == [("pedal", tmp_path / "patches" / "pedal-files-1"),
                                         ("Guitar Lab", tmp_path / "guitarlab" / "GL")]


def test_the_packaged_app_loads_guitar_lab_from_a_wine_prefix(monkeypatch, tmp_path):
    # what main() calls: no root, so the machine-wide Guitar Lab search must run (it once never did when frozen)
    from jmc_guitar_zoom.__main__ import catalog_sources

    home = _isolate(monkeypatch, tmp_path)
    wine = _zd2(home / ".wine/drive_c/users/u/AppData/Roaming/GL")
    _frozen(monkeypatch, tmp_path)
    assert catalog_sources() == [("Guitar Lab", wine)]
    assert catalog_sources([("extra", tmp_path)]) == [("extra", tmp_path)]  # --catalog folders replace the defaults


def test_catalog_sources_with_a_root_keep_the_source_layout(tmp_path):
    from jmc_guitar_zoom.__main__ import catalog_sources

    (tmp_path / "patches" / "pedal-files-1").mkdir(parents=True)
    gl = _zd2(tmp_path / "guitarlab" / "GL")
    assert catalog_sources(None, tmp_path) == [("pedal", tmp_path / "patches" / "pedal-files-1"), ("Guitar Lab", gl)]
