import pytest
from PySide6.QtWidgets import QToolButton

from ui_replies import FIXTURES
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import icons, strings
from zoomstudio.ui.dialogs import ConfirmDialog
from zoomstudio.ui.glass import GlowHost
from zoomstudio.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot):
    w = MainWindow(load_catalog(("pedal", FIXTURES / "catalog")))
    qtbot.addWidget(w)
    return w


def test_menus_live_on_buttons_and_the_undo_shortcuts_belong_to_the_window(window):
    assert window.undo_action in window.edit_button.menu().actions()
    assert window.copy_action in window.library_button.menu().actions()
    assert window.undo_action in window.actions() and window.redo_action in window.actions()
    assert window.undo_action.shortcut().toString() == "Ctrl+Z"


def test_icon_only_buttons_have_names_and_tooltips(window):
    buttons = [window.open_button, window.reload_button, window.open_file_button, window.save_file_button]
    for b in buttons:
        assert isinstance(b, QToolButton) and b.accessibleName() and b.accessibleName() == b.toolTip()
        assert not b.icon().isNull()
    assert {b.accessibleName() for b in buttons} == {strings.OPEN_FOLDER, strings.RELOAD, strings.OPEN_FILE,
                                                     strings.SAVE_FILE}


def test_save_button_glows_only_through_its_host_and_shows_the_reason(window):
    assert isinstance(window.save_button.parentWidget(), GlowHost)
    assert not window.save_button.isEnabled() and strings.SAVE_NEEDS_CONNECTION in window.save_button.toolTip()


def test_every_icon_renders():
    for name in icons.PATHS:
        assert not icons.pixmap(name, "#ffffff", 20).isNull()


def test_confirm_dialog_defaults_to_cancel(qtbot):
    d = ConfirmDialog(None, "t", "x", strings.DISCARD_ACCEPT, danger=True)
    qtbot.addWidget(d)
    assert d.cancel_button.isDefault() and not d.accept_button.isDefault()
    assert d.accept_button.property("danger") is True
