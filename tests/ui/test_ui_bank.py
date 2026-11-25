"""Patch bank screen: stash (free a position), load into any position with swap, drag and drop, safety checks."""
import pytest
from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent

from test_ui_librarian import (_close_windows, B1, HB_ONE, HB_TWO, HDR, M, S, _WINDOWS, catalog, echo, fake_pedal, queue_write, sent,
                               wire)  # noqa: F401 (catalog and _close_windows are fixtures)
from ui_replies import FIXTURES
from jmc_guitar_zoom.device import sysex
from jmc_guitar_zoom.patches.bank import PatchBank
from jmc_guitar_zoom.patches.library import empty_patch
from jmc_guitar_zoom.patches.zptc import build_zptc, parse_zptc
from jmc_guitar_zoom.ui import strings
from jmc_guitar_zoom.ui.bank_screen import MIME_BANK
from jmc_guitar_zoom.ui.dialogs import ConfirmDialog
from jmc_guitar_zoom.ui.main_window import MainWindow
from jmc_guitar_zoom.ui.widgets import MIME_PATCH

EMPTY = build_zptc(empty_patch())
# 42 filler patches, HB One at 43, HB Two at 44, Empty at 45..47, filler after (display numbers = location + 9)
PEDAL = [B1] * 42 + [HB_ONE, HB_TWO, EMPTY, EMPTY, EMPTY] + [B1] * 3


def _lead() -> bytes:
    patch = parse_zptc(HB_ONE)
    patch.name = "Bank Lead"
    return build_zptc(patch)


LEAD = _lead()


def window(qtbot, catalog, tmp_path, patches=None, timeout=0.3):
    from test_ui_librarian import connected

    w, t = connected(qtbot, catalog, tmp_path, patches=patches or PEDAL, timeout=timeout)
    return w, t


@pytest.fixture
def yes(monkeypatch):
    asked = []

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return True

    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(question))
    return asked


@pytest.fixture
def errors():
    return []


def bank_of(w) -> PatchBank:
    return w.bank_store


def names(w):
    return sorted(e.name for e in bank_of(w).list())


def drop(widget, item_or_pos, mime_type, payload: bytes):
    mime = QMimeData()
    mime.setData(mime_type, QByteArray(payload))
    pos = QPointF(item_or_pos)
    event = QDropEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    widget.dropEvent(event)
    return event


def writes(t, since):
    return [d for d in wire(t)[since:] if d.startswith(HDR + b"\x45")]


# ---------------------------------------------------------------------- stash

def test_stash_stores_the_patch_then_writes_empty_with_an_autosave_backup(qtbot, catalog, tmp_path, yes, monkeypatch):
    w, t = window(qtbot, catalog, tmp_path)
    before = len(wire(t))
    seen = []
    real = w._queue_write
    monkeypatch.setattr(w, "_queue_write", lambda items: (seen.append(names(w)), real(items))[1])
    queue_write(t, 44, HB_TWO, sent(EMPTY))
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.stash_position(44)
    assert blocker.args == [[44], 0]
    assert seen == [["HB Two"]]  # the bank file existed before the pedal was touched
    entry = bank_of(w).list()[0]
    assert (entry.name, entry.origin) == ("HB Two", 53)
    assert bank_of(w).read(entry.id) == HB_TWO
    assert wire(t)[before:] == [
        sysex.pc_mode(True, M), sysex.read_patch_request(44, 10, M),
        sysex.write_patch_request(44, sent(EMPTY), 10, M), sysex.read_patch_request(44, 10, M),
        sysex.pc_mode(False, M)]
    backups = sorted((tmp_path / "autosave").glob("044-*.zptc"))
    assert len(backups) == 1 and backups[0].read_bytes() == HB_TWO
    assert w._patches[44].name == "Empty"
    assert "53" in yes[0] and "HB Two" in yes[0] and "banco" in yes[0].lower()


def test_stash_is_refused_for_an_empty_position(qtbot, catalog, tmp_path, yes, errors):
    w, t = window(qtbot, catalog, tmp_path)
    w.error_shown.connect(errors.append)
    before = len(wire(t))
    w.stash_position(45)
    assert errors == [strings.ERR_BANK_NOTHING_TO_KEEP] and yes == []
    assert wire(t)[before:] == [] and bank_of(w).list() == []


def test_stash_keeps_the_bank_entry_when_the_pedal_write_fails(qtbot, catalog, tmp_path, yes, errors):
    w, t = window(qtbot, catalog, tmp_path)
    w.error_shown.connect(errors.append)
    bank, slot = divmod(43, 10)
    from ui_replies import patch_reply
    t.on(HDR + b"\x46", S(patch_reply(bank, slot, HB_TWO)))  # the backup read works, the write is never acknowledged
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.stash_position(44)
    assert blocker.args == [[], 44]
    assert names(w) == ["HB Two"] and w._patches[44].name == "HB Two"
    assert any(strings.ERR_BANK_KEPT_BOTH in e or "banco" in e for e in errors)


# ----------------------------------------------------------------------- load

def test_load_into_a_free_position_writes_it_and_removes_the_bank_entry(qtbot, catalog, tmp_path, yes):
    w, t = window(qtbot, catalog, tmp_path)
    entry = bank_of(w).add(LEAD, origin=20)
    before = len(wire(t))
    queue_write(t, 45, EMPTY, echo(LEAD, catalog))
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.load_from_bank(entry.id, 45)
    assert blocker.args == [[45], 0]
    assert wire(t)[before:] == [
        sysex.pc_mode(True, M), sysex.read_patch_request(45, 10, M),
        sysex.write_patch_request(45, sent(LEAD), 10, M), sysex.read_patch_request(45, 10, M),
        sysex.pc_mode(False, M)]
    assert w._patches[45].name == "Bank Lead" and bank_of(w).list() == []
    assert "54" in yes[0] and "Bank Lead" in yes[0]


def test_load_into_an_occupied_position_moves_the_occupant_to_the_bank_first(qtbot, catalog, tmp_path, yes, monkeypatch):
    w, t = window(qtbot, catalog, tmp_path)
    entry = bank_of(w).add(LEAD, origin=20)
    seen = []
    real = w._queue_write
    monkeypatch.setattr(w, "_queue_write", lambda items: (seen.append(names(w)), real(items))[1])
    queue_write(t, 44, HB_TWO, echo(LEAD, catalog))
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.load_from_bank(entry.id, 44)
    assert blocker.args == [[44], 0]
    assert seen == [["Bank Lead", "HB Two"]]  # the occupant was stored before the write
    assert names(w) == ["HB Two"]  # only after the read-back matched was the loaded entry removed
    assert bank_of(w).read(bank_of(w).list()[0].id) == HB_TWO
    assert w._patches[44].name == "Bank Lead"
    text = yes[0]
    assert "53" in text and "HB Two" in text and "Bank Lead" in text
    assert len(list((tmp_path / "autosave").glob("044-*.zptc"))) == 1


def test_a_failed_pedal_write_keeps_both_patches_in_the_bank(qtbot, catalog, tmp_path, yes, errors):
    w, t = window(qtbot, catalog, tmp_path)
    w.error_shown.connect(errors.append)
    entry = bank_of(w).add(LEAD, origin=20)
    bank, slot = divmod(43, 10)
    from ui_replies import patch_reply
    t.on(HDR + b"\x46", S(patch_reply(bank, slot, HB_TWO)))  # no acknowledgement of the write
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.load_from_bank(entry.id, 44)
    assert blocker.args == [[], 44]
    assert names(w) == ["Bank Lead", "HB Two"] and w._patches[44].name == "HB Two"
    assert errors[-1] == strings.ERR_BANK_KEPT_BOTH or strings.ERR_BANK_KEPT_BOTH in errors


def test_loading_an_unknown_entry_reports_it(qtbot, catalog, tmp_path, yes, errors):
    w, t = window(qtbot, catalog, tmp_path)
    w.error_shown.connect(errors.append)
    before = len(wire(t))
    w.load_from_bank("nope", 45)
    assert len(errors) == 1 and wire(t)[before:] == []


# --------------------------------------------------------------------- blocks

@pytest.mark.parametrize("operation", ["stash", "load"])
def test_both_operations_are_blocked_with_unsaved_edits_on_the_position(qtbot, catalog, tmp_path, yes, errors, operation):
    w, t = window(qtbot, catalog, tmp_path)
    w.error_shown.connect(errors.append)
    entry = bank_of(w).add(LEAD, origin=20)
    edited = parse_zptc(HB_TWO)
    edited.name = "Edited"
    w._stage({44: edited}, "edit")
    before = len(wire(t))
    w.stash_position(44) if operation == "stash" else w.load_from_bank(entry.id, 44)
    assert errors == [strings.err_bank_unsaved(53)] and yes == []
    assert wire(t)[before:] == [] and names(w) == ["Bank Lead"]


@pytest.mark.parametrize("operation", ["stash", "load"])
def test_both_operations_are_blocked_while_not_connected(qtbot, catalog, tmp_path, yes, errors, operation):
    w = MainWindow(catalog, backup_dir=tmp_path / "autosave", library_dir=tmp_path / "patches")
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.error_shown.connect(errors.append)
    entry = w.bank_store.add(LEAD, origin=20)
    w.stash_position(1) if operation == "stash" else w.load_from_bank(entry.id, 1)
    assert errors == [strings.ERR_BANK_OFFLINE] and yes == []
    assert [e.name for e in w.bank_store.list()] == ["Bank Lead"]


@pytest.mark.parametrize("operation", ["stash", "load"])
def test_both_operations_are_blocked_while_patches_are_loading(qtbot, catalog, tmp_path, yes, errors, operation):
    w, t = window(qtbot, catalog, tmp_path)
    w.error_shown.connect(errors.append)
    entry = bank_of(w).add(LEAD, origin=20)
    w._patches_complete = False
    w.stash_position(44) if operation == "stash" else w.load_from_bank(entry.id, 44)
    assert errors == [strings.ERR_BANK_LOADING] and yes == []
    assert names(w) == ["Bank Lead"]


def test_declining_the_confirmation_writes_and_stores_nothing(qtbot, catalog, tmp_path, monkeypatch):
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: False))
    w, t = window(qtbot, catalog, tmp_path)
    entry = bank_of(w).add(LEAD, origin=20)
    before = len(wire(t))
    w.stash_position(44)
    w.load_from_bank(entry.id, 44)
    w.load_from_bank(entry.id, 45)
    assert wire(t)[before:] == [] and names(w) == ["Bank Lead"]
    assert not (tmp_path / "autosave").exists() or list((tmp_path / "autosave").glob("*.zptc")) == []
    assert w._patches[44].name == "HB Two" and w._patches[45].name == "Empty"


# ------------------------------------------------------------------------ UI

def test_the_screen_lists_positions_and_bank_entries_and_filters_them(qtbot, catalog, tmp_path):
    w, t = window(qtbot, catalog, tmp_path)
    bank_of(w).add(LEAD, origin=20)
    bank_of(w).add(HB_ONE, origin=21)
    w.bank_button.click()
    panel = w.bank_panel
    assert panel.isVisibleTo(w) and not w.splitter.isVisibleTo(w)
    assert panel.positions.count() == 50
    assert panel.positions.item(0).data(Qt.ItemDataRole.UserRole + 10) == 10  # first position is shown as 10
    assert panel.positions.item(49).data(Qt.ItemDataRole.UserRole + 10) == 59
    assert sorted(panel.entry_names()) == ["Bank Lead", "HB One"]
    panel.search.setText("lead")
    assert panel.entry_names() == ["Bank Lead"]
    panel.search.setText("")
    w.bank_button.click()
    assert not panel.isVisibleTo(w) and w.splitter.isVisibleTo(w)


def test_every_way_in_opens_the_screen(qtbot, catalog, tmp_path, monkeypatch):
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: False))
    w, t = window(qtbot, catalog, tmp_path)
    w.bank_action.trigger()
    assert w.bank_button.isChecked() and w.bank_panel.isVisibleTo(w)
    w.bank_button.click()
    w.select_location(44)
    w.stash_from_menu_action.trigger()  # the context menu entry: opens the screen on that position and asks
    assert w.bank_button.isChecked() and w.bank_panel.selected_position() == 44


def test_the_buttons_act_on_the_selection_and_show_a_preview(qtbot, catalog, tmp_path, yes, monkeypatch):
    w, t = window(qtbot, catalog, tmp_path)
    entry = bank_of(w).add(LEAD, origin=20)
    w.bank_button.click()
    panel = w.bank_panel
    assert not panel.stash_button.isEnabled() and not panel.load_button.isEnabled()
    panel.select_position(44)
    assert panel.stash_button.isEnabled()
    assert "HB Two" in panel.preview_label.text() and "53" in panel.preview_label.text()
    panel.select_entry(entry.id)
    assert panel.load_button.isEnabled()
    monkeypatch.setattr(panel, "choose_position", lambda current: 45)
    queue_write(t, 45, EMPTY, echo(LEAD, catalog))
    with qtbot.waitSignal(w.queue_finished, timeout=5000):
        panel.load_button.click()
    assert w._patches[45].name == "Bank Lead"
    # both lists were refreshed after the operation
    assert panel.entry_names() == []
    assert panel.positions.item(44).data(Qt.ItemDataRole.UserRole + 11) == "Bank Lead"
    assert w.patch_list.item(44).data(Qt.ItemDataRole.UserRole + 11) == "Bank Lead"


def test_dragging_a_bank_card_onto_a_position_loads_it(qtbot, catalog, tmp_path, yes):
    w, t = window(qtbot, catalog, tmp_path)
    entry = bank_of(w).add(LEAD, origin=20)
    w.bank_button.click()
    lst = w.bank_panel.positions
    queue_write(t, 44, HB_TWO, echo(LEAD, catalog))
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        drop(lst, lst.visualItemRect(lst.item(43)).center(), MIME_BANK, entry.id.encode())
    assert blocker.args == [[44], 0]
    assert w._patches[44].name == "Bank Lead" and names(w) == ["HB Two"]


def test_dragging_a_position_onto_the_bank_stashes_it(qtbot, catalog, tmp_path, yes):
    w, t = window(qtbot, catalog, tmp_path)
    w.bank_button.click()
    cards = w.bank_panel.bank_list
    queue_write(t, 43, HB_ONE, sent(EMPTY))
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        drop(cards, cards.viewport().rect().center(), MIME_PATCH, b"43")
    assert blocker.args == [[43], 0]
    assert names(w) == ["HB One"] and w._patches[43].name == "Empty"


def test_a_drag_over_a_position_highlights_it_and_leaving_clears_it(qtbot, catalog, tmp_path):
    w, t = window(qtbot, catalog, tmp_path)
    w.bank_button.click()
    lst = w.bank_panel.positions
    lst.show_drop_target(43)
    assert lst.drop_row == 43
    lst.show_drop_target(None)
    assert lst.drop_row is None


def test_a_real_drag_move_over_a_position_highlights_only_while_it_can_drop(qtbot, catalog, tmp_path):
    from PySide6.QtGui import QDragMoveEvent

    w, t = window(qtbot, catalog, tmp_path)
    w.bank_button.click()
    lst = w.bank_panel.positions
    mime = QMimeData()
    mime.setData(MIME_BANK, QByteArray(b"x"))
    pos = QPointF(lst.visualItemRect(lst.item(7)).center())
    lst.dragMoveEvent(QDragMoveEvent(pos.toPoint(), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))
    assert lst.drop_row == 7
    other = QMimeData()
    other.setData(MIME_PATCH, QByteArray(b"3"))  # a position over a position: not a bank operation
    lst.dragMoveEvent(QDragMoveEvent(pos.toPoint(), Qt.DropAction.MoveAction, other, Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))
    assert lst.drop_row is None


def test_a_position_dropped_on_a_position_is_not_a_bank_operation(qtbot, catalog, tmp_path, yes):
    w, t = window(qtbot, catalog, tmp_path)
    w.bank_button.click()
    lst = w.bank_panel.positions
    before = len(wire(t))
    drop(lst, lst.visualItemRect(lst.item(7)).center(), MIME_PATCH, b"3")
    assert yes == [] and wire(t)[before:] == []


def test_a_bank_drop_with_a_junk_payload_is_ignored(qtbot, catalog, tmp_path, yes):
    # verifier advisory 1: a non-numeric payload must neither raise nor write
    w, t = window(qtbot, catalog, tmp_path)
    w.bank_button.click()
    cards = w.bank_panel.bank_list
    before = len(t.sent)
    drop(cards, cards.viewport().rect().center(), MIME_PATCH, b"junk")
    assert len(t.sent) == before and names(w) == []


# ------------------------------------------------------- rename and delete entries

def folder_hash(folder) -> str:
    import hashlib

    h = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        h.update(str(path.relative_to(folder)).encode() + (path.read_bytes() if path.is_file() else b"/"))
    return h.hexdigest()


def open_with_entry(qtbot, catalog, tmp_path):
    w, t = window(qtbot, catalog, tmp_path)
    entry = bank_of(w).add(LEAD, origin=20)
    w.bank_button.click()
    w.bank_panel.select_entry(entry.id)
    return w, t, entry


def pick(monkeypatch, panel, name):
    monkeypatch.setattr(panel, "ask_name", lambda current: name)


def test_rename_by_button_renames_the_patch_and_keeps_the_selection(qtbot, catalog, tmp_path, monkeypatch):
    w, t, entry = open_with_entry(qtbot, catalog, tmp_path)
    before = len(wire(t))
    pick(monkeypatch, w.bank_panel, "Renamed")
    w.bank_panel.rename_button.click()
    assert names(w) == ["Renamed"] and w.bank_panel.entry_names() == ["Renamed"]
    assert parse_zptc(bank_of(w).read(bank_of(w).list()[0].id)).name == "Renamed"
    assert w.bank_panel.selected_entry() == bank_of(w).list()[0].id
    assert len(list(bank_of(w).trash_dir().glob("*.zptc"))) == 1 and wire(t)[before:] == []


def test_rename_by_f2_and_by_menu(qtbot, catalog, tmp_path, monkeypatch):
    from PySide6.QtTest import QTest

    w, t, entry = open_with_entry(qtbot, catalog, tmp_path)
    pick(monkeypatch, w.bank_panel, "ViaF2")
    QTest.keyClick(w.bank_panel.bank_list, Qt.Key.Key_F2)
    assert names(w) == ["ViaF2"]
    menu = w.bank_panel.context_menu_for(w.bank_panel.bank_list.item(0))
    pick(monkeypatch, w.bank_panel, "ViaMenu")
    next(a for a in menu.actions() if a.text() == strings.BANK_RENAME).trigger()
    assert names(w) == ["ViaMenu"]


@pytest.mark.parametrize("answer", [None, "", "   ", "Bank Lead"])
def test_a_cancelled_empty_or_unchanged_rename_changes_nothing(qtbot, catalog, tmp_path, monkeypatch, answer):
    w, t, entry = open_with_entry(qtbot, catalog, tmp_path)
    digest = folder_hash(bank_of(w).folder)
    pick(monkeypatch, w.bank_panel, answer)
    w.bank_panel.rename_button.click()
    assert folder_hash(bank_of(w).folder) == digest


def test_a_refused_name_is_reported_and_changes_nothing(qtbot, catalog, tmp_path, errors):
    w, t, entry = open_with_entry(qtbot, catalog, tmp_path)
    w.error_shown.connect(errors.append)
    digest = folder_hash(bank_of(w).folder)
    w.rename_entry(entry.id, "Much too long")
    assert len(errors) == 1 and folder_hash(bank_of(w).folder) == digest


def test_delete_by_button_asks_names_the_trash_and_moves_the_file(qtbot, catalog, tmp_path, yes):
    w, t, entry = open_with_entry(qtbot, catalog, tmp_path)
    before = len(wire(t))
    w.bank_panel.delete_button.click()
    assert "Bank Lead" in yes[0] and str(bank_of(w).trash_dir()) in yes[0]
    assert names(w) == [] and w.bank_panel.entry_names() == []
    assert [p.read_bytes() for p in bank_of(w).trash_dir().glob("*.zptc")] == [LEAD]
    assert wire(t)[before:] == []


def test_delete_by_key_and_by_menu_keeps_a_sensible_selection(qtbot, catalog, tmp_path, yes):
    from PySide6.QtTest import QTest

    w, t = window(qtbot, catalog, tmp_path)
    ids = [bank_of(w).add(LEAD, origin=20 + i, now=f"2026112{i}-101500").id for i in range(3)]
    w.bank_button.click()
    panel = w.bank_panel
    panel.select_row_near(1)
    QTest.keyClick(panel.bank_list, Qt.Key.Key_Delete)
    assert len(bank_of(w).list()) == 2 and panel.bank_list.currentRow() == 1
    menu = panel.context_menu_for(panel.bank_list.item(0))
    next(a for a in menu.actions() if a.text() == strings.BANK_DELETE).trigger()
    assert len(bank_of(w).list()) == 1 and panel.selected_entry() is not None
    assert len(yes) == 2 and len(list(bank_of(w).trash_dir().glob("*.zptc"))) == 2


def test_a_declined_delete_changes_nothing(qtbot, catalog, tmp_path, monkeypatch):
    w, t, entry = open_with_entry(qtbot, catalog, tmp_path)
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: False))
    digest = folder_hash(bank_of(w).folder)
    w.bank_panel.delete_button.click()
    assert folder_hash(bank_of(w).folder) == digest and w.bank_panel.entry_names() == ["Bank Lead"]


def test_rename_and_delete_are_disabled_without_a_selection_and_while_writing(qtbot, catalog, tmp_path, yes, errors):
    w, t, entry = open_with_entry(qtbot, catalog, tmp_path)
    panel = w.bank_panel
    assert panel.rename_button.isEnabled() and panel.delete_button.isEnabled()
    panel.select_entry(None)
    assert not panel.rename_button.isEnabled() and not panel.delete_button.isEnabled()
    panel.select_entry(entry.id)
    w.error_shown.connect(errors.append)
    w._set_saving(True)
    assert not panel.rename_button.isEnabled() and not panel.delete_button.isEnabled()
    w.rename_entry(entry.id, "X")
    w.delete_entry(entry.id)
    assert errors == [strings.ERR_BANK_BUSY] * 2 and names(w) == ["Bank Lead"]
    w._set_saving(False)


def test_rename_dialog_enforces_the_editor_name_rules(qtbot):
    from jmc_guitar_zoom.ui.bank_screen import RenameDialog

    dialog = RenameDialog(None, "Old")
    qtbot.addWidget(dialog)
    assert dialog.edit.text() == "Old" and dialog.edit.maxLength() == 10
    assert dialog.edit.validator().validate("Ñ", 0)[0].name != "Acceptable"
    assert "10" in dialog.hint.text()
