import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStyleOptionViewItem

from ui_replies import FIXTURES
from zoomstudio.effects.catalog import load_catalog
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
    assert PatchCardDelegate().sizeHint(option, window.patch_list.model().index(0, 0)) == QSize(260, CARD_HEIGHT)


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
