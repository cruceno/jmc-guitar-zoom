"""Favourite effects: the store, the star on every card, the filters and the Favoritos section.

Favourites live in a private file per test (the autouse ``private_favorites`` fixture and the explicit store);
the user's real configuration is never read or written.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_ui_effects_manager import BEFORE, PedalFiles, connected_window, names, open_screen
from ui_replies import FIXTURES
from jmc_guitar_zoom.effects.catalog import load_catalog
from jmc_guitar_zoom.ui import favorites as fav_module
from jmc_guitar_zoom.ui import strings as ST
from jmc_guitar_zoom.ui.cards import FAVORITES_KEY, ROLE_FAV, star_rect
from jmc_guitar_zoom.ui.favorites import FavoritesStore
from jmc_guitar_zoom.ui.main_window import MainWindow

COMP, HALL = 16777232, 150994992  # effect IDs of Comp (DYNAMICS) and Hall (REVERB) in the fixtures


@pytest.fixture(scope="module")
def catalog():
    from test_ui_effects_manager import EFFECTS

    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


@pytest.fixture
def store(tmp_path):
    return FavoritesStore(tmp_path / "favorites.json")


@pytest.fixture
def window(qtbot, catalog, store):
    w = MainWindow(catalog, favorites=store)
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.show()
    for group in w.catalog_panel.section_groups():  # the catalog starts folded: open every section for these tests
        w.catalog_panel.toggle_section(group)
    return w


def row_of(panel, name):
    return panel.row_of(name)


def click_star(lst, row):
    item = lst.item(row)
    assert not item.isHidden(), "the card must be in an unfolded section to be clicked"
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=star_rect(lst.visualItemRect(item)).center().toPoint())


# ---------------------------------------------------------------- the store


def test_favorites_survive_a_reload_of_the_store(tmp_path):
    path = tmp_path / "sub" / "favorites.json"
    first = FavoritesStore(path)
    assert first.toggle(COMP) is True
    first.toggle(HALL)
    first.toggle(HALL)
    assert FavoritesStore(path).ids() == {COMP}


@pytest.mark.parametrize("content", ["", "{not json", '{"favorites": "x"}', '[1, 2]', '{"favorites": [1, "a", null, true]}'])
def test_a_corrupt_file_means_no_favorites(tmp_path, content):
    path = tmp_path / "favorites.json"
    path.write_text(content)
    assert FavoritesStore(path).ids() <= {1}  # at worst the one valid integer survives; never a crash
    assert FavoritesStore(tmp_path / "missing.json").ids() == set()


def test_tests_never_use_the_real_config_path(tmp_path_factory, qtbot, catalog):
    real = fav_module.FILE_NAME
    w = MainWindow(catalog)  # no store given: the default one
    qtbot.addWidget(w)
    assert w.favorites.path is not None and w.favorites.path.name == real
    assert "tmp" in str(w.favorites.path) or "pytest" in str(w.favorites.path)
    from PySide6.QtCore import QStandardPaths

    config = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    assert not str(w.favorites.path).startswith(config)


# ---------------------------------------------------------------- catalog panel


def test_click_on_the_star_toggles_a_favorite_and_a_filled_star_is_not_only_colour(window, store):
    panel = window.catalog_panel
    assert panel.item_of("Comp").data(ROLE_FAV) is False
    click_star(panel.list, row_of(panel, "Comp"))
    assert store.is_favorite(COMP) and panel.item_of("Comp").data(ROLE_FAV) is True
    assert panel.section_groups()[0] == FAVORITES_KEY  # it moved to the first section
    click_star(panel.list, row_of(panel, "Comp"))
    assert not store.is_favorite(COMP)


def test_the_f_key_toggles_the_focused_card(qtbot, window, store):
    panel = window.catalog_panel
    panel.list.setCurrentRow(row_of(panel, "Hall"))
    qtbot.keyClick(panel.list, Qt.Key.Key_F)
    assert store.is_favorite(HALL)
    qtbot.keyClick(panel.list, Qt.Key.Key_F)
    assert not store.is_favorite(HALL)


def test_the_context_menu_marks_and_unmarks(window, store):
    panel = window.catalog_panel
    menu = panel.list.context_menu_for(panel.item_of("Comp"))
    assert [a.text() for a in menu.actions()] == [ST.FAVORITE_ADD]
    menu.actions()[0].trigger()
    assert store.is_favorite(COMP)
    assert [a.text() for a in panel.list.context_menu_for(panel.item_of("Comp")).actions()] == [ST.FAVORITE_REMOVE]


def test_the_favorites_filter_combines_with_search_and_group(window, store):
    panel = window.catalog_panel
    store.set_favorite(COMP, True)
    store.set_favorite(HALL, True)
    panel.group_combo.setCurrentIndex(panel.group_combo.findText(ST.FAVORITES))
    assert sorted(panel.visible_names()) == ["Comp", "Hall"]
    panel.search.setText("hal")
    assert panel.visible_names() == ["Hall"]
    panel.search.setText("")
    store.toggle(HALL)  # un-favouriting inside the filter drops it from the list
    assert panel.visible_names() == ["Comp"]


def test_toggling_a_favorite_never_edits_the_patch(window, store):
    window.select_location(44)
    before = window.is_dirty(44)
    panel = window.catalog_panel
    click_star(panel.list, row_of(panel, "Comp"))
    assert store.is_favorite(COMP) and window.is_dirty(44) == before is False


# ---------------------------------------------------------------- effects screen


@pytest.fixture
def screen(qtbot, monkeypatch, catalog, tmp_path, store):
    pedal_files = PedalFiles(BEFORE)
    pedal_files.install(monkeypatch)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, pedal_files)
    w.favorites.path = store.path
    return w, open_screen(qtbot, w)


def test_favorites_form_the_first_section_of_the_accordion(screen):
    w, panel = screen
    w.favorites.set_favorite(HALL, True)
    w.favorites.set_favorite(COMP, True)
    assert panel.section_groups("installed")[0] == "\0favorites"
    assert panel.section_count("installed", "\0favorites") == 2
    assert "REVERB" not in panel.section_groups("installed")  # a favourite is listed once, in Favoritos
    assert panel.section_count("installed", "DYNAMICS") == 1  # OptComp stays in its own group
    header = panel.installed_list.item(0)
    assert ST.FAVORITES in header.data(Qt.ItemDataRole.AccessibleTextRole)


def test_the_screens_favorites_filter_and_star_toggle(qtbot, screen):
    w, panel = screen
    panel.group_combo.setCurrentIndex(panel.group_combo.findData("\0favorites"))
    assert names(panel, "installed") == [] and names(panel, "available") == []
    panel.group_combo.setCurrentIndex(0)
    panel.select_effect("HALL.ZD2")
    qtbot.keyClick(panel.installed_list, Qt.Key.Key_F)
    assert w.favorites.is_favorite(HALL)
    panel.group_combo.setCurrentIndex(panel.group_combo.findData("\0favorites"))
    assert names(panel, "installed") == ["HALL.ZD2"]
    panel.search.setText("zzz")
    assert names(panel, "installed") == []


def test_the_screen_star_by_click_and_menu_and_selection_is_kept(screen):
    w, panel = screen
    panel.select_effect("COMP.ZD2")
    row = next(i for i in range(panel.installed_list.count())
               if (e := panel.installed_list.item(i).data(Qt.ItemDataRole.UserRole + 30)) and e.file == "COMP.ZD2")
    item = panel.installed_list.item(row)
    QTest.mouseClick(panel.installed_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=star_rect(panel.installed_list.visualItemRect(item)).center().toPoint())
    assert w.favorites.is_favorite(COMP)
    assert panel.selected_name() == "COMP.ZD2"  # the card moved into Favoritos; it is still the selection
    cards = panel.installed_list
    moved = next(cards.item(i) for i in range(cards.count())
                 if (e := cards.item(i).data(Qt.ItemDataRole.UserRole + 30)) and e.file == "COMP.ZD2")
    cards.context_menu_for(moved).actions()[0].trigger()
    assert not w.favorites.is_favorite(COMP)
