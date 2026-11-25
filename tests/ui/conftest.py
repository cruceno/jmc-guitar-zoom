import pytest
from zoomstudio.ui.dialogs import ConfirmDialog


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A dirty window asks before closing; a modal box would hang the offscreen run.

    Default answer: Discard. Tests that care replace ``ConfirmDialog.ask`` themselves.
    Being autouse, this fixture is torn down after ``qtbot`` closed its widgets.
    """
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: True))


@pytest.fixture(autouse=True)
def private_favorites(monkeypatch, tmp_path_factory):
    """The default favourites file lives in the user's real config: every test gets a private one instead."""
    from zoomstudio.ui import favorites

    path = tmp_path_factory.mktemp("config") / favorites.FILE_NAME
    monkeypatch.setattr(favorites, "default_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def private_bank(monkeypatch, tmp_path_factory):
    """The default patch bank is ``patches/bank`` of the real workspace: every test gets a private folder instead."""
    from zoomstudio.patches import bank

    folder = tmp_path_factory.mktemp("bank-default")
    monkeypatch.setattr(bank, "default_dir", lambda: folder)
    return folder
