"""The daily throttle of the background update check (stored with the settings, never in the real config)."""
import json

from zoomstudio.ui import settings
from zoomstudio.ui.settings import DAY_SECONDS, UpdateStore


def test_a_first_run_is_due(tmp_path):
    assert UpdateStore(tmp_path / "updates.json").due(1_000_000.0)


def test_a_check_less_than_a_day_old_is_not_due_and_a_day_later_is(tmp_path):
    store = UpdateStore(tmp_path / "updates.json")
    store.mark_checked(1_000_000.0)
    assert not store.due(1_000_000.0 + DAY_SECONDS - 1)
    assert store.due(1_000_000.0 + DAY_SECONDS)


def test_the_last_check_survives_a_restart(tmp_path):
    UpdateStore(tmp_path / "updates.json").mark_checked(5000.0)
    assert UpdateStore(tmp_path / "updates.json").last_check == 5000.0


def test_a_last_check_in_the_future_is_due_again(tmp_path):  # a clock that went back must not silence the check
    store = UpdateStore(tmp_path / "updates.json")
    store.mark_checked(2_000_000.0)
    assert store.due(1_000_000.0)


def test_a_corrupt_or_foreign_file_means_never_checked(tmp_path):
    path = tmp_path / "updates.json"
    for text in ("not json", json.dumps({"last_check": "yesterday"}), json.dumps([1]), json.dumps({"last_check": True})):
        path.write_text(text)
        assert UpdateStore(path).last_check is None and UpdateStore(path).due(10.0)


def test_an_unwritable_folder_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    UpdateStore(blocker / "sub" / "updates.json").mark_checked(1.0)  # must not raise


def test_the_default_file_sits_next_to_the_target_file_and_is_redirected_by_the_tests():
    assert settings.update_path().name == "updates.json"
    assert settings.update_path().parent == settings.default_path().parent
