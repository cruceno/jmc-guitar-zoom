import pytest
from PySide6.QtWidgets import QMessageBox


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A dirty window asks before closing; a modal box would hang the offscreen run.

    Default answer: Discard. Tests that care replace ``QMessageBox.question`` themselves.
    Being autouse, this fixture is torn down after ``qtbot`` closed its widgets.
    """
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard))
