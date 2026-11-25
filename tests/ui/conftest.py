import pytest
from zoomstudio.ui.dialogs import ConfirmDialog


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A dirty window asks before closing; a modal box would hang the offscreen run.

    Default answer: Discard. Tests that care replace ``ConfirmDialog.ask`` themselves.
    Being autouse, this fixture is torn down after ``qtbot`` closed its widgets.
    """
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: True))
