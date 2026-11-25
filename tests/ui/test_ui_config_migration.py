"""The settings kept under the former name are copied once to the new config folder (tmp folders only)."""
from jmc_guitar_zoom.ui.config_migration import FILES, migrate_legacy_config


def make(folder, **contents):
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in contents.items():
        (folder / name).write_text(text)


def test_files_of_the_old_folder_are_copied_and_the_originals_stay(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    make(old, **{"favorites.json": "[1]", "target.json": "{}", "updates.json": "{}"})
    assert migrate_legacy_config(new, old) == list(FILES)
    assert (new / "favorites.json").read_text() == "[1]"
    assert (old / "favorites.json").read_text() == "[1]" and len(list(old.iterdir())) == 3


def test_a_file_already_in_the_new_folder_is_never_overwritten(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    make(old, **{"favorites.json": "old", "target.json": "old"})
    make(new, **{"favorites.json": "mine"})
    assert migrate_legacy_config(new, old) == ["target.json"]
    assert (new / "favorites.json").read_text() == "mine"


def test_a_missing_old_folder_changes_nothing(tmp_path):
    assert migrate_legacy_config(tmp_path / "new", tmp_path / "absent") == []
    assert not (tmp_path / "new").exists()


def test_a_second_run_copies_nothing(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    make(old, **{"updates.json": "{}"})
    assert migrate_legacy_config(new, old) == ["updates.json"]
    assert migrate_legacy_config(new, old) == []
