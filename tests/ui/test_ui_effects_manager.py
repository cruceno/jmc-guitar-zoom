"""The effects manager screen, driven through the window: lists, actions, confirmations and the worker round trip.

The pedal's files are an in-memory store behind ``PedalClient.read_file/list_files/disk_usage/write_file/
delete_file``; PC mode still goes through a scripted FakeTransport. No MIDI hardware is touched.
"""
import dataclasses
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from ui_replies import FIXTURES, HDR, S, fake_pedal, patch_reply
from zoomstudio.device import PedalClient
from zoomstudio.device import sysex
from zoomstudio.device.errors import PedalFileNotFound
from zoomstudio.device.sysex import DiskUsage
from zoomstudio.effects import flst
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.effects.installer import MEMORY_MARGIN
from zoomstudio.ui import strings as ST
from zoomstudio.ui.dialogs import ConfirmDialog
from zoomstudio.ui.effects_manager import ROLE_ENTRY
from zoomstudio.ui.main_window import MainWindow

EFFECTS = Path(__file__).parents[1] / "effects" / "fixtures"
BEFORE = (EFFECTS / "flst" / "before-12st.ZT2").read_bytes()
AFTER = (EFFECTS / "flst" / "after-12st.ZT2").read_bytes()
BACKUP = FIXTURES / "backup"
PATCHES = [(BACKUP / "001.zptc").read_bytes(), (FIXTURES / "53-HB-Jazz.zptc").read_bytes()]
ON_PEDAL = ["COMP.ZD2", "FDDLXR1U.ZD2", "FDDX1X12.ZD2", "GTGEQ71U.ZD2", "HALL.ZD2", "OPTCOMP.ZD2"]
TOTAL, FREE = 3_087_950, 143_150


class PedalFiles:
    """The pedal's file system, plugged into PedalClient's file methods."""

    def __init__(self, flst_bytes: bytes, names=ON_PEDAL, free: int = FREE) -> None:
        self.files = {flst.FLST_NAME: flst_bytes, **{n: b"\x00" * 64 for n in names}}
        self.free = free

    def install(self, monkeypatch) -> None:
        def read_file(_client, name, timeout=None):
            if name not in self.files:
                raise PedalFileNotFound(name)
            return self.files[name]

        def write_file(_client, name, data, timeout=None):
            self.free += len(self.files.get(name, b"")) - len(data)
            self.files[name] = bytes(data)

        def delete_file(_client, name, timeout=None):
            self.free += len(self.files.pop(name, b""))

        monkeypatch.setattr(PedalClient, "read_file", read_file)
        monkeypatch.setattr(PedalClient, "write_file", write_file)
        monkeypatch.setattr(PedalClient, "delete_file", delete_file)
        monkeypatch.setattr(PedalClient, "list_files", lambda _client, timeout=None: sorted(self.files))
        monkeypatch.setattr(PedalClient, "disk_usage", lambda _client, timeout=None: DiskUsage(TOTAL, self.free))


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


def connected_window(qtbot, monkeypatch, catalog, tmp_path, pedal_files: PedalFiles, a1_ids=None, member=0x11, **kw):
    pedal_files.install(monkeypatch)
    transport = fake_pedal(PATCHES, member=member)
    for _ in range(30):  # every state read, install and removal runs in its own PC mode
        transport.on(sysex.pc_mode(True, 0x6E), S(HDR + b"\x00\x00"))
        transport.on(sysex.pc_mode(False, 0x6E), S(HDR + b"\x00\x00"))
    w = MainWindow(catalog, a1_ids=a1_ids, transport_factory=lambda: transport, backup_dir=tmp_path, **kw)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    return w


def open_screen(qtbot, w):
    panel = w.effects_panel
    with qtbot.waitSignal(panel.state_shown, timeout=5000):
        w.open_effects_screen()
    return panel


def names(panel, which):
    return sorted(getattr(panel, f"{which}_names")())


@pytest.fixture
def screen(qtbot, monkeypatch, catalog, tmp_path):
    pedal_files = PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, pedal_files)
    return w, open_screen(qtbot, w), pedal_files


def test_lists_are_built_from_the_pedal_list_and_the_local_files(screen):
    _w, panel, _files = screen
    assert names(panel, "installed") == ON_PEDAL
    # 160_COMP and 12Strings: listed with the flag off and a local .zd2 to upload
    assert names(panel, "available") == ["160_COMP.ZD2", "MDL_12ST.ZD2"]


def test_once_the_flag_is_set_the_effect_moves_to_installed(qtbot, monkeypatch, catalog, tmp_path):
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(AFTER, ON_PEDAL + ["MDL_12ST.ZD2"]))
    panel = open_screen(qtbot, w)
    assert "MDL_12ST.ZD2" in names(panel, "installed")
    assert names(panel, "available") == ["160_COMP.ZD2"]


def test_an_installed_flag_without_the_file_is_listed_as_missing_its_file(qtbot, monkeypatch, catalog, tmp_path):
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE, ON_PEDAL[:-1]))
    panel = open_screen(qtbot, w)
    assert "OPTCOMP.ZD2" in names(panel, "installed")  # flagged: it is listed, not hidden
    assert panel.missing_names() == ["OPTCOMP.ZD2"]
    assert "OPTCOMP.ZD2" not in names(panel, "available")  # its flag is set: nothing to install


def test_effects_the_list_does_not_contain_are_shown_but_cannot_be_installed(qtbot, monkeypatch, catalog, tmp_path):
    unlisted = dataclasses.replace(catalog[0x1800030], effect_id=0x1800099, filename="ZZNEW_100.zd2")
    pedal_files = PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, {**catalog, unlisted.effect_id: unlisted}, tmp_path, pedal_files)
    panel = open_screen(qtbot, w)
    assert names(panel, "available") == ["160_COMP.ZD2", "MDL_12ST.ZD2", "ZZNEW.ZD2"]
    panel.select_effect("ZZNEW.ZD2")
    assert not panel.install_button.isEnabled()  # the pedal's list has no record of it


def test_only_effects_of_the_a1_four_are_offered(qtbot, monkeypatch, catalog, tmp_path):
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE), a1_ids={0x14400190})
    panel = open_screen(qtbot, w)
    assert names(panel, "available") == ["MDL_12ST.ZD2"]


def test_search_filters_both_lists(screen):
    _w, panel, _files = screen
    panel.search.setText("hall")
    assert names(panel, "installed") == ["HALL.ZD2"]
    assert names(panel, "available") == []
    assert panel.available_empty.isVisibleTo(panel)
    panel.search.setText("")
    assert len(names(panel, "installed")) == len(ON_PEDAL)


def test_selecting_a_card_shows_the_extended_spanish_description(screen, catalog):
    _w, panel, _files = screen
    panel.select_effect("HALL.ZD2")
    assert panel.detail_name.text() == "Hall"
    assert panel.detail_text.text() == panel.description_of("HALL.ZD2") != ""
    from zoomstudio.effects.i18n import effect_description
    assert panel.detail_text.text() == effect_description(catalog[0x9000030])


def test_the_memory_bar_and_its_label_are_separate_widgets(screen):
    _w, panel, _files = screen
    assert panel.memory_bar.isTextVisible() is False
    assert panel.memory_bar.value() == round((1 - FREE / TOTAL) * 100)
    assert panel.memory_label.text() == ST.effects_memory(TOTAL - FREE, TOTAL, FREE)


def test_install_is_disabled_with_the_reason_when_memory_is_short(qtbot, monkeypatch, catalog, tmp_path):
    size = catalog[0x14400190].path.stat().st_size
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE, free=size + MEMORY_MARGIN - 1))
    panel = open_screen(qtbot, w)
    panel.select_effect("MDL_12ST.ZD2")
    assert not panel.install_button.isEnabled()
    assert panel.reason_label.text() == ST.effects_install_blocked(
        size + MEMORY_MARGIN, size, MEMORY_MARGIN, size + MEMORY_MARGIN - 1)
    assert panel.reason_label.isVisibleTo(panel)


def test_install_is_enabled_with_exactly_the_margin(qtbot, monkeypatch, catalog, tmp_path):
    size = catalog[0x14400190].path.stat().st_size
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE, free=size + MEMORY_MARGIN))
    panel = open_screen(qtbot, w)
    panel.select_effect("MDL_12ST.ZD2")
    assert panel.install_button.isEnabled()


def test_remove_is_blocked_for_an_effect_in_use_with_a_short_neutral_reason(screen):
    _w, panel, _files = screen
    panel.select_effect("HALL.ZD2")  # the second patch (display 11, "HB Jazz") uses it
    assert not panel.remove_button.isEnabled()
    assert panel.reason_label.text() == ST.EFFECTS_IN_USE_SHORT == "En uso: no se puede quitar"
    assert panel.reason_label.property("blocking") is False  # not red: the list above says which patches
    panel.select_effect("OPTCOMP.ZD2")  # both patches
    assert not panel.remove_button.isEnabled()
    panel.select_effect("COMP.ZD2")
    assert panel.remove_button.isEnabled()


def test_the_usage_list_shows_exactly_the_patches_using_the_effect_in_order(screen):
    _w, panel, _files = screen
    panel.select_effect("OPTCOMP.ZD2")
    assert panel.usage_locations() == [1, 2]
    assert panel.usage_title.text() == "Usado en 2 patches"
    assert panel.usage_list.isVisibleTo(panel) and not panel.usage_empty.isVisibleTo(panel)
    first = panel.usage_list.item(0)
    assert first.data(Qt.ItemDataRole.AccessibleTextRole) == ST.effects_usage_card_name(10, "AG D-28")
    panel.select_effect("HALL.ZD2")
    assert panel.usage_locations() == [2] and panel.usage_title.text() == "Usado en 1 patch"


def click_usage_card(panel, row=0):
    from PySide6.QtTest import QTest

    item = panel.usage_list.item(row)
    QTest.mouseClick(panel.usage_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=panel.usage_list.visualItemRect(item).center())


def test_clicking_a_patch_card_closes_the_screen_and_selects_that_patch(screen):
    w, panel, _files = screen
    panel.select_effect("HALL.ZD2")
    click_usage_card(panel)
    assert not w.effects_toggle.isChecked() and not panel.isVisibleTo(w)
    assert w.patch_list.currentRow() == 1  # location 2 (display 11, "HB Jazz")


def test_enter_on_a_patch_card_does_the_same(screen, qtbot):
    w, panel, _files = screen
    panel.select_effect("OPTCOMP.ZD2")
    panel.usage_list.setFocus()
    panel.usage_list.setCurrentRow(0)
    qtbot.keyClick(panel.usage_list, Qt.Key.Key_Return)
    assert not w.effects_toggle.isChecked() and w.patch_list.currentRow() == 0


def test_an_effect_no_patch_uses_gets_a_calm_message_that_is_not_red(screen):
    _w, panel, _files = screen
    panel.select_effect("COMP.ZD2")
    assert panel.usage_empty.isVisibleTo(panel) and not panel.usage_list.isVisibleTo(panel)
    assert panel.usage_title.text() == ST.EFFECTS_USAGE_NONE == "Ningún patch usa este efecto"
    assert ST.EFFECTS_USAGE_NONE_NOTE in panel.usage_empty_note.text()
    assert not panel.usage_empty_icon.pixmap().isNull()
    for widget in panel.usage_box.findChildren(QWidget) + [panel.reason_label]:
        assert not widget.property("blocking") and widget.property("role") != "error"


def test_while_patches_are_not_all_read_the_section_says_why_not_in_red(screen):
    w, panel, _files = screen
    panel.select_effect("COMP.ZD2")
    w.reload()
    assert panel.usage_note.isVisibleTo(panel) and panel.usage_note.text() == ST.EFFECTS_PATCHES_INCOMPLETE
    assert not panel.usage_list.isVisibleTo(panel) and not panel.usage_empty.isVisibleTo(panel)
    assert not panel.usage_note.property("blocking")
    assert not panel.remove_button.isEnabled()


def test_remove_is_blocked_until_every_patch_is_loaded(screen, qtbot):
    w, panel, _files = screen
    panel.select_effect("COMP.ZD2")
    assert panel.remove_button.isEnabled()
    w.reload()  # a reload empties the list before the patches come back (the button itself is locked)
    assert not panel.remove_button.isEnabled()
    assert panel.reason_label.text() == ST.EFFECTS_USAGE_PENDING_SHORT


def test_remove_is_blocked_while_a_patch_has_unsaved_edits(screen):
    w, panel, _files = screen
    w.select_location(1)
    w.name_edit.setText("Otro")
    w.name_edit.textEdited.emit("Otro")
    panel.select_effect("COMP.ZD2")
    assert not panel.remove_button.isEnabled()
    assert panel.reason_label.text() == ST.EFFECTS_USAGE_PENDING_SHORT
    assert panel.usage_note.text() == ST.EFFECTS_UNSAVED_PATCHES


def test_install_asks_first_then_uploads_and_refreshes_the_state(screen, qtbot, monkeypatch, tmp_path):
    w, panel, files = screen
    asked = []
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda parent, title, text, *a, **k: asked.append((title, text)) or True))
    panel.select_effect("MDL_12ST.ZD2")
    with qtbot.waitSignal(panel.state_shown, timeout=5000):
        panel.install_button.click()
    assert len(asked) == 1 and "copia de seguridad" in asked[0][1] and "FLST_SEQ.ZT2" in asked[0][1]
    assert files.files["MDL_12ST.ZD2"] == catalog_bytes()
    assert files.files[flst.FLST_NAME] == AFTER
    assert "MDL_12ST.ZD2" in names(panel, "installed") and "MDL_12ST.ZD2" not in names(panel, "available")
    assert len(list((tmp_path / "effects").glob("*FLST_SEQ.ZT2"))) == 1  # the backup of the list
    assert w.memory_value.text() == f"{round((1 - files.free / TOTAL) * 100)} %"
    assert not files.free == FREE


def catalog_bytes() -> bytes:
    return (EFFECTS / "lib" / "MDL_12ST_100.zd2").read_bytes()


def test_declining_the_confirmation_writes_nothing(screen, qtbot, monkeypatch):
    _w, panel, files = screen
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: False))
    panel.select_effect("MDL_12ST.ZD2")
    panel.install_button.click()
    qtbot.wait(200)
    assert files.files[flst.FLST_NAME] == BEFORE and "MDL_12ST.ZD2" not in files.files


def test_remove_asks_first_then_deletes_and_refreshes_the_state(screen, qtbot, monkeypatch, tmp_path):
    w, panel, files = screen
    asked = []
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda parent, title, text, *a, **k: asked.append(text) or True))
    panel.select_effect("COMP.ZD2")
    with qtbot.waitSignal(panel.state_shown, timeout=5000):
        panel.remove_button.click()
    assert len(asked) == 1 and "copia de seguridad" in asked[0]
    assert "COMP.ZD2" not in files.files
    assert not flst.is_installed(files.files[flst.FLST_NAME], "COMP.ZD2")
    assert "COMP.ZD2" not in names(panel, "installed") and "COMP.ZD2" in names(panel, "available")
    assert len(list((tmp_path / "effects").glob("*FLST_SEQ.ZT2"))) == 1


def test_a_failed_install_goes_through_the_error_path(qtbot, monkeypatch, catalog, tmp_path):
    size = catalog[0x14400190].path.stat().st_size
    files = PedalFiles(BEFORE, free=size + MEMORY_MARGIN)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files)
    panel = open_screen(qtbot, w)
    panel.select_effect("MDL_12ST.ZD2")
    files.free = 10  # the pedal has less memory by the time the install runs
    with qtbot.waitSignal(w.error_shown, timeout=5000) as blocker:
        panel.install_button.click()
    assert blocker.args[0].startswith("No se pudo instalar MDL_12ST.ZD2")
    qtbot.waitUntil(lambda: panel.install_button.isEnabled() or not panel.reason_label.text().startswith("Instalando"),
                    timeout=3000)
    assert files.files[flst.FLST_NAME] == BEFORE


def test_without_a_connection_the_screen_explains_it_and_offers_nothing(qtbot, catalog, tmp_path):
    w = MainWindow(catalog, a1_ids=None, backup_dir=tmp_path)
    qtbot.addWidget(w)
    w.open_effects_screen()
    panel = w.effects_panel
    assert panel.message_label.text() == ST.EFFECTS_OFFLINE
    assert panel.message_label.isVisibleTo(panel)
    assert names(panel, "installed") == [] and names(panel, "available") == []
    assert not panel.install_button.isEnabled() and not panel.remove_button.isEnabled()


def test_disconnecting_with_the_screen_open_shows_the_offline_message(screen, qtbot):
    w, panel, _files = screen
    w.disconnect_button.click()
    qtbot.waitUntil(lambda: panel.message_label.text() == ST.EFFECTS_OFFLINE, timeout=3000)
    assert names(panel, "installed") == []


def test_editing_is_locked_while_the_screen_is_open(screen):
    w, panel, _files = screen
    assert panel.isVisibleTo(w) and not w.splitter.isVisibleTo(w)
    assert not w.splitter.isEnabled()
    assert not w.edit_button.isEnabled() and not w.library_button.isEnabled()
    assert not w.save_button.isEnabled() and not w.tuner_button.isEnabled()
    assert w.effects_toggle.isChecked()
    panel.close_button.click()
    assert not panel.isVisibleTo(w) and w.splitter.isVisibleTo(w) and w.splitter.isEnabled()
    assert w.edit_button.isEnabled() and w.library_button.isEnabled() and not w.effects_toggle.isChecked()


def test_the_tuner_cannot_start_while_the_screen_is_open(screen):
    w, _panel, _files = screen
    assert not w.tuner_button.isEnabled()


# ---------------------------------------------------------------- ways into the screen


def test_the_library_menu_opens_the_screen_through_the_top_bar_toggle(qtbot, monkeypatch, catalog, tmp_path):
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE))
    action = next(a for a in w.library_button.menu().actions() if a.text() == ST.LIBRARY_EFFECTS)
    assert action.isEnabled()
    with qtbot.waitSignal(w.effects_panel.state_shown, timeout=5000):
        action.trigger()
    assert w.effects_toggle.isChecked() and w.effects_panel.isVisibleTo(w)


def test_the_catalog_button_opens_the_screen_through_the_top_bar_toggle(qtbot, monkeypatch, catalog, tmp_path):
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE))
    button = w.catalog_panel.manage_button
    assert button.text() == ST.CATALOG_MANAGE and not button.icon().isNull()
    assert "instala o quita efectos" in button.toolTip().lower()
    with qtbot.waitSignal(w.effects_panel.state_shown, timeout=5000):
        button.click()
    assert w.effects_toggle.isChecked() and w.effects_panel.isVisibleTo(w)
    assert not hasattr(w, "effects_button")  # the bar has no «Efectos» button any more


# ---------------------------------------------------------------- groups


def click_header(panel, which, group):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    cards = getattr(panel, f"{which}_list")
    item = cards.item(panel.section_header_row(which, group))
    QTest.mouseClick(cards.viewport(), Qt.MouseButton.LeftButton, pos=cards.visualItemRect(item).center())


def test_each_list_has_one_section_per_group_with_its_count(screen):
    _w, panel, _files = screen
    assert panel.section_groups("installed") == ["AMP", "CABINET", "DYNAMICS", "FILTER", "REVERB"]
    assert [panel.section_count("installed", g) for g in panel.section_groups("installed")] == [1, 1, 2, 1, 1]
    assert panel.section_groups("available") == ["AG MODEL", "DYNAMICS"]
    assert all(panel.section_expanded("installed", g) for g in panel.section_groups("installed"))
    header = panel.installed_list.item(panel.section_header_row("installed", "DYNAMICS"))
    assert header.data(Qt.ItemDataRole.AccessibleTextRole) == ST.effects_section_name(ST.group_label("DYNAMICS"), 2, True)
    assert panel.installed_names() == sorted(ON_PEDAL, key=lambda f: ["FDDLXR1U.ZD2", "FDDX1X12.ZD2", "COMP.ZD2",
                                                                       "OPTCOMP.ZD2", "GTGEQ71U.ZD2", "HALL.ZD2"].index(f))


def test_clicking_a_header_folds_and_unfolds_its_cards(screen):
    _w, panel, _files = screen
    row = panel.section_header_row("installed", "DYNAMICS")
    cards = [panel.installed_list.item(row + 1), panel.installed_list.item(row + 2)]
    click_header(panel, "installed", "DYNAMICS")
    assert not panel.section_expanded("installed", "DYNAMICS")
    assert all(c.isHidden() for c in cards)
    assert panel.section_expanded("installed", "AMP")  # the others are untouched
    click_header(panel, "installed", "DYNAMICS")
    assert panel.section_expanded("installed", "DYNAMICS") and not any(c.isHidden() for c in cards)


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Space])
def test_a_header_toggles_from_the_keyboard(qtbot, screen, key):
    _w, panel, _files = screen
    panel.installed_list.setCurrentRow(panel.section_header_row("installed", "AMP"))
    qtbot.keyClick(panel.installed_list, key)
    assert not panel.section_expanded("installed", "AMP")
    qtbot.keyClick(panel.installed_list, key)
    assert panel.section_expanded("installed", "AMP")


def test_a_folded_section_stays_folded_while_the_screen_is_open(screen):
    _w, panel, _files = screen
    panel.toggle_section("installed", "AMP")
    panel.search.setText("hall")
    panel.search.setText("")
    assert not panel.section_expanded("installed", "AMP")


def test_the_group_filter_limits_both_lists(screen):
    _w, panel, _files = screen
    assert panel.group_combo.itemText(0) == ST.ALL_GROUPS
    panel.group_combo.setCurrentIndex(panel.group_combo.findData("DYNAMICS"))
    assert names(panel, "installed") == ["COMP.ZD2", "OPTCOMP.ZD2"]
    assert names(panel, "available") == ["160_COMP.ZD2"]
    assert panel.section_groups("installed") == ["DYNAMICS"]
    panel.group_combo.setCurrentIndex(0)
    assert len(names(panel, "installed")) == len(ON_PEDAL)


def test_search_hides_the_sections_without_a_match_and_counts_follow(screen):
    _w, panel, _files = screen
    panel.search.setText("comp")
    assert panel.section_groups("installed") == ["DYNAMICS"]
    assert panel.section_count("installed", "DYNAMICS") == 2
    assert panel.section_groups("available") == ["DYNAMICS"]
    panel.search.setText("optcomp")
    assert panel.section_count("installed", "DYNAMICS") == 1
    assert panel.section_groups("available") == []


def test_install_and_remove_work_from_a_grouped_list(qtbot, monkeypatch, catalog, tmp_path):
    pedal_files = PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, pedal_files)
    panel = open_screen(qtbot, w)
    panel.toggle_section("available", "AG MODEL")  # folded: selecting must still work
    panel.select_effect("MDL_12ST.ZD2")
    assert panel.selected_name() == "MDL_12ST.ZD2" and panel.section_expanded("available", "AG MODEL")
    assert panel.install_button.isVisibleTo(panel) and panel.install_button.isEnabled()
    with qtbot.waitSignal(panel.state_shown, timeout=8000):
        panel.install_button.click()
    assert "MDL_12ST.ZD2" in names(panel, "installed")
    assert "AG MODEL" in panel.section_groups("installed")
    panel.select_effect("HALL.ZD2")
    assert panel.remove_button.isVisibleTo(panel)


# ---------------------------------------------------------------- repair: flagged installed, file missing


def broken_window(qtbot, monkeypatch, catalog, tmp_path, free=FREE):
    """MDL_12ST is flagged installed in the list (``after-12st``) but its file is not on the pedal."""
    files = PedalFiles(AFTER, ON_PEDAL, free=free)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files)
    return w, open_screen(qtbot, w), files


def test_an_effect_without_its_file_is_marked_in_text_tooltip_and_accessible_name(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = broken_window(qtbot, monkeypatch, catalog, tmp_path)
    assert panel.missing_names() == ["MDL_12ST.ZD2"]
    assert "AG MODEL" in panel.section_groups("installed")  # inside its group section
    item = next(panel.installed_list.item(i) for i in range(panel.installed_list.count())
                if panel.installed_list.item(i).data(ROLE_ENTRY) is not None
                and panel.installed_list.item(i).data(ROLE_ENTRY).file == "MDL_12ST.ZD2")
    assert ST.EFFECTS_MISSING == "Falta el archivo"
    assert ST.EFFECTS_MISSING in item.toolTip()
    assert ST.EFFECTS_MISSING in item.data(Qt.ItemDataRole.AccessibleTextRole)


def test_repair_replaces_remove_and_is_enabled_with_a_local_copy(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = broken_window(qtbot, monkeypatch, catalog, tmp_path)
    panel.select_effect("MDL_12ST.ZD2")
    assert panel.repair_button.text() == ST.EFFECTS_REPAIR
    assert panel.repair_button.isVisibleTo(panel) and panel.repair_button.isEnabled()
    assert not panel.remove_button.isVisibleTo(panel) and not panel.install_button.isVisibleTo(panel)
    panel.select_effect("COMP.ZD2")  # a normal installed effect keeps Quitar
    assert panel.remove_button.isVisibleTo(panel) and not panel.repair_button.isVisibleTo(panel)


def test_repair_is_disabled_without_a_local_copy(qtbot, monkeypatch, catalog, tmp_path):
    no_copy = {k: (dataclasses.replace(v, path=None) if v.effect_id == 0x14400190 else v) for k, v in catalog.items()}
    _w, panel, _files = broken_window(qtbot, monkeypatch, no_copy, tmp_path)
    panel.select_effect("MDL_12ST.ZD2")
    assert panel.repair_button.isVisibleTo(panel) and not panel.repair_button.isEnabled()
    assert panel.reason_label.text() == "No hay una copia local de este efecto"


def test_repair_is_disabled_when_memory_is_short(qtbot, monkeypatch, catalog, tmp_path):
    size = catalog[0x14400190].path.stat().st_size
    _w, panel, _files = broken_window(qtbot, monkeypatch, catalog, tmp_path, free=size + MEMORY_MARGIN - 1)
    panel.select_effect("MDL_12ST.ZD2")
    assert not panel.repair_button.isEnabled()
    assert panel.reason_label.text() == ST.effects_install_blocked(size + MEMORY_MARGIN, size, MEMORY_MARGIN,
                                                                   size + MEMORY_MARGIN - 1)


def test_repair_asks_first_then_uploads_only_the_file_and_refreshes(qtbot, monkeypatch, catalog, tmp_path):
    w, panel, files = broken_window(qtbot, monkeypatch, catalog, tmp_path)
    asked = []
    monkeypatch.setattr(ConfirmDialog, "ask",
                        staticmethod(lambda parent, title, text, *a, **k: asked.append(text) or True))
    panel.select_effect("MDL_12ST.ZD2")
    with qtbot.waitSignal(panel.state_shown, timeout=5000):
        panel.repair_button.click()
    assert len(asked) == 1
    text = asked[0].lower()
    assert "solo se sube el archivo" in text and "no se modifica la lista" in text and "copia de seguridad" in text
    assert files.files["MDL_12ST.ZD2"] == catalog_bytes()
    assert files.files[flst.FLST_NAME] == AFTER  # the list is untouched
    assert len(list((tmp_path / "effects").glob("*FLST_SEQ.ZT2"))) == 1  # the backup of the list
    assert panel.missing_names() == []
    assert "MDL_12ST.ZD2" in names(panel, "installed")
    assert w.memory_value.text() == f"{round((1 - files.free / TOTAL) * 100)} %"
    assert w.statusBar().currentMessage() == ST.effects_repaired_ok("MDL_12ST.ZD2")  # not "installed"


def test_declining_the_repair_writes_nothing(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, files = broken_window(qtbot, monkeypatch, catalog, tmp_path)
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: False))
    panel.select_effect("MDL_12ST.ZD2")
    panel.repair_button.click()
    qtbot.wait(200)
    assert "MDL_12ST.ZD2" not in files.files and files.files[flst.FLST_NAME] == AFTER
    assert not (tmp_path / "effects").exists()


def test_a_failed_repair_goes_through_the_error_path(qtbot, monkeypatch, catalog, tmp_path):
    size = catalog[0x14400190].path.stat().st_size
    w, panel, files = broken_window(qtbot, monkeypatch, catalog, tmp_path, free=size + MEMORY_MARGIN)
    panel.select_effect("MDL_12ST.ZD2")
    files.free = 10  # the pedal has less memory by the time the repair runs
    with qtbot.waitSignal(w.error_shown, timeout=5000) as blocker:
        panel.repair_button.click()
    assert blocker.args[0].startswith("No se pudo reparar MDL_12ST.ZD2")
    assert "MDL_12ST.ZD2" not in files.files


# ---------------------------------------------------------------- pedal filter: the full catalog, installable or not

A1, G5N = 0x6E001100, 0x6E000000
MDL_12ST, COMP_160 = 0x14400190, 0x1800030  # 12Strings and 160 Comp of the local lib (see the tests above)


def pedal_registry(extra_a1=()):
    from zoomstudio.effects.models import PedalModel

    return {A1: PedalModel(A1, "A1 FOUR", frozenset({MDL_12ST, 0x1000010, 0x1000090, 0x400002C, 0x2000054, 0x9000030, *extra_a1})),
            G5N: PedalModel(G5N, "G5n", frozenset({MDL_12ST, COMP_160}))}


def pedal_screen(qtbot, monkeypatch, catalog, tmp_path, registry=None, files=None):
    from zoomstudio.effects import models as pm

    monkeypatch.setattr(pm, "SUPPORTED_MODELS", {A1})
    files = files or PedalFiles(BEFORE)
    files.install(monkeypatch)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files, models=registry or pedal_registry())
    return w, open_screen(qtbot, w), files


def entry_item(panel, which, file):
    cards = getattr(panel, f"{which}_list")
    return next(cards.item(i) for i in range(cards.count())
                if cards.item(i).data(ROLE_ENTRY) is not None and cards.item(i).data(ROLE_ENTRY).file == file)


def test_the_pedal_filter_defaults_to_the_connected_pedal_and_offers_all_and_the_others(qtbot, monkeypatch, catalog, tmp_path):
    w, panel, _files = pedal_screen(qtbot, monkeypatch, catalog, tmp_path)
    combo = panel.pedal_combo
    assert combo.currentData() == A1 and combo.itemText(combo.currentIndex()) == "A1 FOUR (conectada)"
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert ST.EFFECTS_ALL_PEDALS == "Todos los pedales" and ST.EFFECTS_ALL_PEDALS in texts and "G5n" in texts
    assert names(panel, "installed") == ON_PEDAL  # the installed list does not depend on the filter
    assert "160_COMP.ZD2" not in names(panel, "available")  # a G5n effect: not shown for the A1 FOUR
    assert "MDL_12ST.ZD2" in names(panel, "available")


def test_all_pedals_shows_the_full_catalog_with_a_badge_on_what_the_pedal_cannot_install(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = pedal_screen(qtbot, monkeypatch, catalog, tmp_path)
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData("all"))
    assert "160_COMP.ZD2" in names(panel, "available") and "MDL_12ST.ZD2" in names(panel, "available")
    other = entry_item(panel, "available", "160_COMP.ZD2")
    assert ST.not_compatible_with("A1 FOUR") == "No compatible con A1 FOUR"
    assert ST.not_compatible_with("A1 FOUR") in other.toolTip() and ST.not_compatible_with("A1 FOUR") in other.data(Qt.ItemDataRole.AccessibleTextRole)
    assert ST.not_compatible_with("A1 FOUR") not in entry_item(panel, "available", "MDL_12ST.ZD2").toolTip()


def test_a_non_compatible_effect_has_install_disabled_with_the_reason_and_keeps_its_description_and_star(qtbot, monkeypatch, catalog, tmp_path):
    w, panel, _files = pedal_screen(qtbot, monkeypatch, catalog, tmp_path)
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData("all"))
    panel.select_effect("160_COMP.ZD2")
    assert panel.install_button.isVisibleTo(panel) and not panel.install_button.isEnabled()
    assert panel.reason_label.text() == ST.effects_not_compatible_reason("A1 FOUR")
    assert panel.reason_label.property("blocking") is False
    assert panel.description_of("160_COMP.ZD2") and panel.detail_text.text() == panel.description_of("160_COMP.ZD2")
    item = entry_item(panel, "available", "160_COMP.ZD2")
    panel.available_list.favorite_toggled.emit(item)  # the star still works
    assert w.favorites.is_favorite(COMP_160)


def test_an_effect_the_pedals_list_does_not_contain_is_shown_but_cannot_be_installed(qtbot, monkeypatch, catalog, tmp_path):
    unlisted = dataclasses.replace(catalog[MDL_12ST], effect_id=0x1800099, filename="ZZNEW_100.zd2")
    registry = pedal_registry(extra_a1=(0x1800099,))
    files = PedalFiles(BEFORE)
    files.install(monkeypatch)
    w = connected_window(qtbot, monkeypatch, {**catalog, unlisted.effect_id: unlisted}, tmp_path, files, models=registry)
    panel = open_screen(qtbot, w)
    panel.select_effect("ZZNEW.ZD2")
    assert not panel.install_button.isEnabled() and panel.reason_label.text() == ST.EFFECTS_NOT_IN_PEDAL_LIST


def test_an_installable_effect_still_installs_from_the_filtered_list(qtbot, monkeypatch, catalog, tmp_path):
    w, panel, files = pedal_screen(qtbot, monkeypatch, catalog, tmp_path)
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData("all"))
    panel.select_effect("MDL_12ST.ZD2")
    assert panel.install_button.isEnabled()
    with qtbot.waitSignal(panel.state_shown, timeout=5000):
        panel.install_button.click()
    assert files.files[flst.FLST_NAME] == AFTER and "MDL_12ST.ZD2" in names(panel, "installed")


def test_grouping_search_and_favorites_work_with_the_pedal_filter(qtbot, monkeypatch, catalog, tmp_path):
    w, panel, _files = pedal_screen(qtbot, monkeypatch, catalog, tmp_path)
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData(G5N))  # effects of the G5n, installable or not
    assert set(names(panel, "available")) == {"160_COMP.ZD2", "MDL_12ST.ZD2"}
    panel.search.setText("comp")
    assert names(panel, "available") == ["160_COMP.ZD2"] and panel.section_groups("available") == ["DYNAMICS"]
    panel.search.setText("")
    w.favorites.set_favorite(COMP_160, True)
    assert panel.section_groups("available")[0] == "\0favorites"
    panel.group_combo.setCurrentIndex(panel.group_combo.findData("\0favorites"))
    assert names(panel, "available") == ["160_COMP.ZD2"]
