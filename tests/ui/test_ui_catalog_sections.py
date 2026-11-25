"""The editor's effect catalog grouped in collapsible sections (same accordion as the effects screen)."""
import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest

from ui_replies import FIXTURES
from jmc_guitar_zoom.effects.catalog import load_catalog
from jmc_guitar_zoom.effects.models import A1_FOUR, PedalModel
from jmc_guitar_zoom.ui import strings as ST
from jmc_guitar_zoom.ui.cards import FAVORITES_KEY, ROLE_SECTION
from jmc_guitar_zoom.ui.favorites import FavoritesStore
from jmc_guitar_zoom.ui.main_window import MainWindow
from jmc_guitar_zoom.ui.mime import MIME_EFFECT

COMP, HALL = 16777232, 150994992


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"))


@pytest.fixture
def window(qtbot, catalog, tmp_path):
    everything = {A1_FOUR: PedalModel(A1_FOUR, "A1 FOUR", frozenset(catalog))}  # the target runs every fixture effect
    w = MainWindow(catalog, models=everything, favorites=FavoritesStore(tmp_path / "f.json"))
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.show()
    return w


def click_header(panel, group):
    lst = panel.list
    item = lst.item(panel.section_header_row(group))
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=lst.visualItemRect(item).center())


def test_one_section_per_group_with_its_count_in_group_order(window):
    panel = window.catalog_panel
    assert panel.section_groups() == ["AMP", "CABINET", "DYNAMICS", "FILTER", "REVERB"]
    assert [panel.section_count(g) for g in panel.section_groups()] == [1, 1, 2, 1, 1]
    header = panel.list.item(panel.section_header_row("DYNAMICS"))
    assert header.data(Qt.ItemDataRole.AccessibleTextRole) == ST.effects_section_name(ST.group_label("DYNAMICS"), 2, False)
    assert sorted(panel.visible_names()) == ["Comp", "FD DLXR", "FD-DX1x12", "Gt GEQ 7", "Hall", "OptComp"]


def test_every_group_starts_collapsed_when_nothing_is_selected(window):
    panel = window.catalog_panel
    assert not any(panel.section_expanded(g) for g in panel.section_groups())
    assert panel.item_of("Comp").isHidden()


def test_the_group_of_the_selected_chain_effect_starts_expanded(window):
    window.select_location(44)  # HB Jazz: its first effect, OptComp, is a DYNAMICS one
    panel = window.catalog_panel
    assert [g for g in panel.section_groups() if panel.section_expanded(g)] == ["DYNAMICS"]
    assert not panel.item_of("Comp").isHidden() and panel.item_of("Hall").isHidden()
    window.select_tile(6)  # Hall: REVERB opens too, and DYNAMICS stays as it was
    assert panel.section_expanded("REVERB") and panel.section_expanded("DYNAMICS")


def test_clicking_a_header_toggles_it_and_the_state_is_kept(window):
    panel = window.catalog_panel
    click_header(panel, "REVERB")
    assert panel.section_expanded("REVERB") and not panel.item_of("Hall").isHidden()
    panel.group_combo.setCurrentIndex(0)
    panel.search.setText("x")
    panel.search.setText("")
    assert panel.section_expanded("REVERB")  # the user's choice survives a rebuild
    click_header(panel, "REVERB")
    assert not panel.section_expanded("REVERB")


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Space])
def test_a_header_toggles_from_the_keyboard_without_adding_an_effect(window, qtbot, key):
    window.select_location(44)
    window.select_tile(6)
    before = [s.effect_id for s in window.current_patch.effects]
    panel = window.catalog_panel
    panel.list.setCurrentRow(panel.section_header_row("AMP"))
    qtbot.keyClick(panel.list, key)
    assert panel.section_expanded("AMP")
    qtbot.keyClick(panel.list, key)
    assert not panel.section_expanded("AMP")
    assert [s.effect_id for s in window.current_patch.effects] == before


def test_search_expands_matching_sections_hides_the_rest_and_clearing_restores(window):
    panel = window.catalog_panel
    click_header(panel, "AMP")  # the user opened AMP only
    panel.search.setText("hal")
    assert panel.section_groups() == ["REVERB"] and panel.section_expanded("REVERB")
    assert panel.visible_names() == ["Hall"]
    panel.search.setText("")
    assert panel.section_groups() == ["AMP", "CABINET", "DYNAMICS", "FILTER", "REVERB"]
    assert [g for g in panel.section_groups() if panel.section_expanded(g)] == ["AMP"]


def test_group_combo_a1_filter_and_favorites_work_with_sections(window):
    panel = window.catalog_panel
    panel.group_combo.setCurrentText(ST.group_label("DYNAMICS"))
    assert panel.section_groups() == ["DYNAMICS"] and panel.section_expanded("DYNAMICS")
    assert sorted(panel.visible_names()) == ["Comp", "OptComp"]
    panel.group_combo.setCurrentIndex(0)
    window.favorites.set_favorite(HALL, True)
    assert panel.section_groups()[0] == FAVORITES_KEY and "REVERB" not in panel.section_groups()
    assert panel.section_expanded(FAVORITES_KEY)  # favourites start open
    panel.group_combo.setCurrentIndex(panel.group_combo.findText(ST.FAVORITES))
    assert panel.section_groups() == [FAVORITES_KEY] and panel.visible_names() == ["Hall"]


def test_add_by_enter_by_button_and_double_click_work_from_a_grouped_list(window, qtbot):
    window.select_location(44)
    window.select_tile(6)
    panel = window.catalog_panel
    click_header(panel, "DYNAMICS") if not panel.section_expanded("DYNAMICS") else None
    panel.list.setCurrentRow(panel.row_of("Comp"))
    assert panel.target_button.isEnabled()
    panel.target_button.click()
    assert window.current_patch.effects[6].effect_id == COMP
    window.undo()
    qtbot.keyClick(panel.list, Qt.Key.Key_Return)
    assert window.current_patch.effects[6].effect_id == COMP
    window.undo()
    panel.list.itemDoubleClicked.emit(panel.item_of("Comp"))
    assert window.current_patch.effects[6].effect_id == COMP


def test_a_header_has_no_effect_to_add_or_drag(window):
    window.select_location(44)
    window.select_tile(6)
    panel = window.catalog_panel
    panel.list.setCurrentRow(panel.section_header_row("AMP"))
    assert not panel.target_button.isEnabled() and not panel.detail_card.isVisibleTo(panel)
    assert not panel.list.mimeData([panel.list.item(panel.section_header_row("AMP"))]).hasFormat(MIME_EFFECT)


def test_dragging_an_effect_from_a_grouped_list_still_carries_its_id(window):
    mime = window.catalog_panel.list.mimeData([window.catalog_panel.item_of("Comp")])
    assert int(bytes(mime.data(MIME_EFFECT))) == COMP


def test_the_catalog_count_counts_effects_not_headers(window):
    panel = window.catalog_panel
    assert panel.count_label.text() == ST.compatible_count(6, "A1 FOUR")


def test_arrow_keys_land_on_headers_and_skip_folded_cards(window, qtbot):
    panel = window.catalog_panel
    click_header(panel, "DYNAMICS")  # unfold the two-card section
    panel.list.setCurrentRow(panel.section_header_row("DYNAMICS"))
    qtbot.keyClick(panel.list, Qt.Key.Key_Down)
    assert panel.list.currentItem().data(Qt.ItemDataRole.UserRole + 20)["group"] == "DYNAMICS"
    qtbot.keyClick(panel.list, Qt.Key.Key_Down)
    qtbot.keyClick(panel.list, Qt.Key.Key_Down)  # past the section's two cards: the next header, not a folded card
    assert panel.list.currentItem().data(ROLE_SECTION)[0] == "FILTER"
