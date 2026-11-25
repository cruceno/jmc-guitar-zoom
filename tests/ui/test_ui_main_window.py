import pytest
from PySide6.QtCore import Qt

from ui_replies import FIXTURES, fake_pedal
from zoomstudio.device.messages import SysexMessage
from zoomstudio.effects.catalog import a1four_effect_ids, load_catalog
from zoomstudio.ui import strings
from zoomstudio.ui.main_window import MainWindow

CATALOG_DIR = FIXTURES / "catalog"
BACKUP = FIXTURES / "backup"
HB = (FIXTURES / "53-HB-Jazz.zptc").read_bytes()


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", CATALOG_DIR))


@pytest.fixture
def window(qtbot, catalog):
    w = MainWindow(catalog, a1_ids=a1four_effect_ids(FIXTURES / "AllZDL7_2.lst"))
    qtbot.addWidget(w)
    w.load_offline(BACKUP)
    return w


def item_texts(lst):
    return [lst.item(i).text() for i in range(lst.count())]


def test_offline_folder_lists_fifty_slots_with_display_numbers(window):
    texts = item_texts(window.patch_list)
    assert len(texts) == 50
    assert texts[0].split()[0] == "10" and texts[-1].split()[0] == "59"
    # location 44 is shown as 53; 001 is shown as 10
    assert window.patch_list.item(43).text().split()[0] == "53"
    assert "10" in texts[0] and window.patch_list.item(0).data(Qt.ItemDataRole.UserRole) == 1
    # slots without a file are greyed
    assert window.is_empty_slot(5) and not window.is_empty_slot(1)
    assert window.patch_list.item(4).foreground().color() != window.patch_list.item(0).foreground().color()
    assert strings.NOT_CONNECTED.lower() in window.connection_label.text().lower()
    assert "backup" in window.connection_label.text()


def test_selecting_hb_jazz_shows_five_tiles_two_wide(window):
    window.select_location(44)
    tiles = [t for t in window.chain_tiles() if not t.is_empty]
    assert [t.effect_name for t in tiles] == ["OptComp", "FD DLXR", "FD-DX1x12", "Gt GEQ 7", "Hall"]
    assert [t.is_wide for t in tiles] == [False, True, False, True, False]
    assert [t.span for t in tiles] == [1, 2, 1, 2, 1]
    assert all(t.is_enabled_effect for t in tiles)
    assert tiles[1].group == "AMP"
    assert window.current_patch.name == "HB Jazz"


def test_empty_slots_are_shown_as_empty_tiles(window):
    window.select_location(1)  # backup 001: not a full chain
    tiles = window.chain_tiles()
    assert tiles, "a patch always shows its chain"
    patch = window.current_patch
    real = [s for s in patch.effects if not s.is_placeholder]
    assert len([t for t in tiles if not t.is_empty]) == len(real)


def test_parameter_panel_names_ranges_and_values(window):
    window.select_location(44)
    window.select_tile(1)  # FD DLXR
    rows = window.param_rows()
    assert [r.name for r in rows] == ["Input", "Bass", "Treble", "Gain", "VOL", "Depth", "Speed"]
    assert [r.spin.maximum() for r in rows] == [1, 90, 90, 90, 90, 90, 100]
    assert [r.spin.value() for r in rows] == [0, 42, 28, 38, 75, 0, 40]
    assert [r.dial.value() for r in rows] == [r.spin.value() for r in rows]
    assert all(r.dial.minimum() == 0 for r in rows)
    window.select_tile(6)  # Hall (slot indexes count the wide fillers: 2 and 5)
    hall = window.param_rows()
    assert [(r.name, r.spin.maximum(), r.spin.value()) for r in hall] == [
        ("PreD", 99, 20), ("Decay", 29, 11), ("Mix", 100, 24), ("Tail", 1, 1)]
    window.select_tile(4)  # Gt GEQ 7: band centre frequencies as names, 24 = flat
    assert [r.name for r in window.param_rows()][:2] == ["100", "200"]


def test_editing_a_knob_marks_dirty_and_sends_nothing(qtbot, catalog):
    transport = fake_pedal([HB])
    w = MainWindow(catalog, a1_ids=None)
    qtbot.addWidget(w)
    w.load_offline(BACKUP)
    w.select_location(44)
    assert not w.is_dirty(44)
    w.select_tile(1)
    bass = w.param_rows()[1]
    bass.dial.setValue(60)
    assert bass.spin.value() == 60  # dial and spin box stay in sync
    assert w.current_patch.effects[1].params[1] == 60
    assert w.is_dirty(44) and not w.is_dirty(1)
    assert "*" in w.patch_list.item(43).text()
    bass.spin.setValue(10)
    assert w.current_patch.effects[1].params[1] == 10
    assert not [m for m in transport.sent if isinstance(m, SysexMessage)]


def test_toggling_effect_on_off_marks_dirty(window):
    window.select_location(44)
    window.chain_tiles()[0].power.click()
    assert window.current_patch.effects[0].enabled is False
    assert window.is_dirty(44)


def test_dirty_edit_survives_reselecting_the_patch(window):
    window.select_location(44)
    window.select_tile(1)
    window.param_rows()[1].spin.setValue(77)
    window.select_location(1)
    window.select_location(44)
    window.select_tile(1)
    assert window.param_rows()[1].spin.value() == 77


def test_catalog_search_and_a1_filter(window):
    panel = window.catalog_panel
    assert set(panel.visible_names()) == {"Comp", "FD DLXR", "FD-DX1x12", "Gt GEQ 7", "Hall", "OptComp"}
    panel.search.setText("gt")
    assert panel.visible_names() == ["Gt GEQ 7"]
    panel.search.setText("")
    panel.a1_check.setChecked(True)  # FD-DX1x12 and OptComp are not in the A1 FOUR list
    assert set(panel.visible_names()) == {"Comp", "FD DLXR", "Gt GEQ 7", "Hall"}
    panel.group_combo.setCurrentText(strings.group_label("AMP"))
    assert panel.visible_names() == ["FD DLXR"]
    panel.a1_check.setChecked(False)
    panel.group_combo.setCurrentText(strings.ALL_GROUPS)
    assert len(panel.visible_names()) == 6


def test_catalog_rows_show_dsp_load_installed_flag_and_svg(window):
    panel = window.catalog_panel
    panel.search.setText("Hall")
    text = panel.list.item(0).text()
    assert "Hall" in text and "%" in text
    assert strings.BADGE_ON_PEDAL in text  # fixture directory is labelled "pedal"
    panel.list.setCurrentRow(0)
    assert panel.preview_has_image()
    panel.search.setText("FD DLXR")  # has no SVG in the fixtures
    panel.list.setCurrentRow(0)
    assert not panel.preview_has_image()


def test_connect_loads_patches_from_a_fake_pedal(qtbot, catalog):
    transport = fake_pedal([(BACKUP / "001.zptc").read_bytes(), HB], disk=(1000, 250))
    w = MainWindow(catalog, a1_ids=None, transport_factory=lambda: transport)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    assert w.patch_list.item(1).text().split()[1:3] == ["HB", "Jazz"]
    assert "A1 FOUR" in w.connection_label.text() and "1.00" in w.connection_label.toolTip()
    qtbot.waitUntil(lambda: w.memory_bar.value() == 75, timeout=3000)
    assert not w.connect_button.isEnabled() and w.disconnect_button.isEnabled()
    w.close()


def test_worker_error_goes_to_status_bar(qtbot, catalog):
    from zoomstudio.device.transport import FakeTransport

    w = MainWindow(catalog, a1_ids=None, transport_factory=lambda: FakeTransport(), pedal_timeout=0.05)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.error_shown, timeout=3000):
        w.connect_button.click()
    assert w.statusBar().currentMessage()
    assert w.connect_button.isEnabled()
    w.close()


def test_catalog_button_enter_and_double_click_all_apply_the_effect(window):
    from PySide6.QtTest import QTest

    window.select_location(44)
    window.select_tile(6)
    panel = window.catalog_panel
    panel.search.setText("Comp")
    panel.list.setCurrentRow(panel.visible_names().index("Comp"))
    assert panel.target_button.text() == strings.catalog_target(6, False, False) and panel.target_button.isEnabled()
    comp = panel.list.currentItem().data(Qt.ItemDataRole.UserRole)
    panel.target_button.click()
    assert window.current_patch.effects[6].effect_id == comp
    window.undo()
    QTest.keyClick(panel.list, Qt.Key.Key_Return)
    assert window.current_patch.effects[6].effect_id == comp


def test_catalog_starts_without_the_a1_filter_and_marks_effects_in_the_chain(window):
    window.select_location(44)
    panel = window.catalog_panel
    assert not panel.a1_check.isChecked() and panel.target_button.text()
    from zoomstudio.ui.cards import ROLE_EFFECT

    flags = {panel.list.item(i).data(ROLE_EFFECT)["name"]: panel.list.item(i).data(ROLE_EFFECT)["in_chain"]
             for i in range(panel.list.count())}
    assert flags["Hall"] is True and flags["Comp"] is False
