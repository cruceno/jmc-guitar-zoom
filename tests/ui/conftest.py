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


@pytest.fixture(autouse=True)
def private_target(monkeypatch, tmp_path_factory):
    """Same for the last target pedal: a private file per test, never the user's config."""
    from zoomstudio.ui import settings

    path = tmp_path_factory.mktemp("config-target") / settings.FILE_NAME
    monkeypatch.setattr(settings, "default_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def no_effect_list_read_after_connect(monkeypatch):
    """After the patches the editor reads the pedal's effect list (a PC-mode session with file reads). Most tests
    script exact traffic and have no pedal files, so they run without that read; the tests of the installed
    state (``test_ui_install_indicators``) put it back."""
    from zoomstudio.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_load_installed_state", lambda self: None)


@pytest.fixture(scope="session", autouse=True)
def gc_on_the_gui_thread_only(qapp):
    """The suite runs with the app's GC policy: a worker thread's collection crashed PySide (see ``gc_guard``)."""
    import gc

    from zoomstudio.ui import gc_guard

    gc_guard.install(qapp)
    yield
    gc.enable()  # the timer dies with the application
