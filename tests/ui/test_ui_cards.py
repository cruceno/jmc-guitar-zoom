import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStyleOptionViewItem

from ui_replies import FIXTURES
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import strings, tokens
from zoomstudio.ui.cards import CARD_HEIGHT, ROLE_DIRTY, ROLE_NAME, ROLE_NUMBER, ROLE_STRIP, PatchCardDelegate
from zoomstudio.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot):
    w = MainWindow(load_catalog(("pedal", FIXTURES / "catalog")))
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.show()
    return w


def test_cards_are_56_px_tall(window):
    option = QStyleOptionViewItem()
    option.rect.setSize(QSize(260, 10))
    assert PatchCardDelegate().sizeHint(option, window.patch_list.model().index(0, 0)).height() == CARD_HEIGHT  # the width is the list's to give


def test_strip_lists_one_block_per_effect_with_its_slots(window):
    window.select_location(44)
    tiles = [t for t in window.chain_tiles() if not t.is_empty]
    item = window.patch_list.item(43)
    assert item.data(ROLE_STRIP) == [(t.group, t.span, t.is_enabled_effect) for t in tiles]
    assert item.data(ROLE_NUMBER) == 53 and item.data(ROLE_NAME) == "HB Jazz"


def test_empty_locations_have_no_strip_and_edits_mark_the_card(window):
    assert window.patch_list.item(4).data(ROLE_STRIP) is None
    window.select_location(44)
    window.rename_patch("Crystal")
    item = window.patch_list.item(43)
    assert item.data(ROLE_DIRTY) is True and "*" in item.text() and item.data(ROLE_NAME) == "Crystal"


def test_list_paints_with_the_delegate(window):
    window.select_location(44)
    image = window.patch_list.viewport().grab().toImage()
    assert not image.isNull() and any(image.pixelColor(x, 30).alpha() for x in range(0, 200, 20))


def test_parameter_cards_show_range_and_default_and_keep_dial_and_spin_in_sync(window):
    window.select_location(44)
    window.select_tile(1)
    rows = window.param_rows()
    assert len(rows) == 7 and 1 <= window.params.columns <= 7  # the cards reflow with the width
    assert rows[1].range_label.text() == strings.param_range(rows[1].maximum, rows[1].default)
    rows[1].dial.setValue(60)
    assert rows[1].spin.value() == 60 and rows[1].dial.default_value == rows[1].default


def test_reset_button_restores_the_default_of_the_current_parameter(window):
    window.select_location(44)
    window.select_tile(1)
    row = window.param_rows()[1]
    row.spin.setValue(77)
    assert window.params.reset_button.isEnabled() and row.current
    window.params.reset_button.click()
    assert row.spin.value() == row.default and window.current_patch.effects[1].params[1] == row.default


def test_knob_draws_the_value_arc_in_the_accent_colour(window):
    window.select_location(44)
    window.select_tile(1)
    knob = window.param_rows()[1].dial
    knob.setValue(knob.maximum())
    image = knob.grab().toImage()
    accent = tokens.color("knob-arc-value").rgb()
    assert any(image.pixelColor(x, y).rgb() == accent for x in range(image.width()) for y in range(image.height()))
