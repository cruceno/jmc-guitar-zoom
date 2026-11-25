import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from ui_replies import FIXTURES
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot):
    w = MainWindow(load_catalog(("pedal", FIXTURES / "catalog")))
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.show()
    w.activateWindow()
    qtbot.waitActive(w)
    w.select_location(44)
    w.select_tile(0)
    w.chain_tiles()[0].body.setFocus()
    return w


def names(w):
    return [t.effect_name for t in w.chain_tiles() if not t.is_empty]


def test_arrows_select_the_neighbouring_pedal_and_move_the_focus(window):
    QTest.keyClick(window.chain_tiles()[0].body, Qt.Key.Key_Right)
    second = window.chain_tiles()[1]
    assert window.chain.selected_slot == second.slot_index
    QTest.keyClick(second.body, Qt.Key.Key_Left)
    assert window.chain.selected_slot == window.chain_tiles()[0].slot_index


def test_home_and_end_jump_to_the_extremes(window):
    QTest.keyClick(window.chain_tiles()[0].body, Qt.Key.Key_End)
    assert window.chain.selected_slot == window.chain_tiles()[-1].slot_index
    QTest.keyClick(window.chain_tiles()[-1].body, Qt.Key.Key_Home)
    assert window.chain.selected_slot == window.chain_tiles()[0].slot_index


def test_ctrl_arrows_move_the_effect_and_it_can_be_undone(window):
    before = names(window)
    QTest.keyClick(window.chain_tiles()[0].body, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert names(window)[:2] == [before[1], before[0]]
    moved = window.chain_tiles()[1]
    assert window.chain.selected_slot == moved.slot_index
    window.undo()
    assert names(window) == before


def test_ctrl_left_on_the_first_pedal_changes_nothing(window):
    QTest.keyClick(window.chain_tiles()[0].body, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert not window.is_dirty(44)


def test_only_the_selected_pedal_is_a_tab_stop(window):
    policies = [t.body.focusPolicy() for t in window.chain_tiles()]
    assert policies[0] == Qt.FocusPolicy.StrongFocus
    assert all(p == Qt.FocusPolicy.ClickFocus for p in policies[1:])
