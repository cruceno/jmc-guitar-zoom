import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QMessageBox

from zoomstudio.ui import strings
from zoomstudio.ui.dialogs import ConfirmDialog

from ui_replies import FIXTURES, HDR, S, fake_pedal, patch_reply, queue_save
from zoomstudio.device import sysex
from zoomstudio.device.messages import SysexMessage
from zoomstudio.device.transport import FakeTransport
from zoomstudio.effects.catalog import a1four_effect_ids, load_catalog
from zoomstudio.patches import edit
from zoomstudio.patches.model import WIDE_FILLER_ID
from zoomstudio.patches.zptc import build_zptc, parse_zptc
from zoomstudio.ui.main_window import MainWindow
from zoomstudio.ui.widgets import MIME_EFFECT, MIME_SLOT

CATALOG_DIR = FIXTURES / "catalog"
BACKUP = FIXTURES / "backup"
HB_BYTES = (FIXTURES / "53-HB-Jazz.zptc").read_bytes()
B1 = (BACKUP / "001.zptc").read_bytes()
COMP, DLXR, HALL = 0x1000010, 0x400002C, 0x9000030


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", CATALOG_DIR))


@pytest.fixture
def window(qtbot, catalog, tmp_path):
    w = MainWindow(catalog, a1_ids=a1four_effect_ids(FIXTURES / "AllZDL7_2.lst") | {0x1000080, 0x500002A},
                   backup_dir=tmp_path / "autosave")
    qtbot.addWidget(w)
    w.load_offline(BACKUP)
    w.select_location(44)
    return w


def ids(w):
    return [s.effect_id for s in w.current_patch.effects]


def undo_cycle(w, before):
    """The edit is dirty and undoable; undo restores ``before`` and clears dirty, redo re-applies.

    Leaves the window undone (``before`` restored).
    """
    after = w.current_patch
    assert w.is_dirty(44)
    w.undo()
    assert w.current_patch == before and not w.is_dirty(44)
    w.redo()
    assert w.current_patch == after and w.is_dirty(44)
    w.undo()
    assert w.current_patch == before and not w.is_dirty(44)


def test_rename_is_dirty_undoable_and_validated(window):
    before = window.current_patch
    window.rename_patch("Crystal")
    assert window.current_patch.name == "Crystal"
    assert "Crystal" in window.patch_list.item(43).text() and "*" in window.patch_list.item(43).text()
    undo_cycle(window, before)
    errors = []
    window.error_shown.connect(errors.append)
    window.rename_patch("way too long name")
    window.rename_patch("café")
    assert window.current_patch.name == "HB Jazz" and len(errors) == 2 and not window.is_dirty(44)


def test_name_edit_widget_limits_to_ten_printable_ascii(window, qtbot):
    window.name_edit.clear()
    qtbot.keyClicks(window.name_edit, "abcdefghijKL")
    assert window.name_edit.text() == "abcdefghij" and window.current_patch.name == "abcdefghij"
    validator = window.name_edit.validator()
    assert validator.validate("caf\u00e9", 0)[0] == validator.State.Invalid
    assert validator.validate("ok name ~!", 0)[0] == validator.State.Acceptable


def test_volume_edit_is_dirty_and_undoable(window):
    before = window.current_patch
    window.volume_spin.setValue(64)
    assert window.current_patch.volume == 64
    undo_cycle(window, before)
    assert window.volume_spin.value() == before.volume


def test_param_edit_undoable_and_merges_a_drag(window):
    window.select_tile(1)
    before = window.current_patch
    row = window.param_rows()[1]
    for v in (50, 51, 52, 60):  # one drag = one undo step
        row.dial.setValue(v)
    assert window.current_patch.effects[1].params[1] == 60
    undo_cycle(window, before)
    assert window.current_patch.effects[1].params[1] == 42


def test_toggle_edit_undoable(window):
    before = window.current_patch
    window.chain_tiles()[0].power.click()
    assert window.current_patch.effects[0].enabled is False
    undo_cycle(window, before)
    assert window.chain_tiles()[0].power.isChecked()


def test_replace_effect_gets_catalog_defaults_and_is_undoable(window):
    before = window.current_patch
    window.replace_effect(6, COMP)  # Hall -> Comp
    patch = window.current_patch
    assert patch.effects[6].effect_id == COMP
    assert patch.effects[6].params[:4] == [6, 0, 6, 80]  # Sense, ATTCK, Tone, VOL defaults
    assert patch.effects[6].enabled
    assert window.chain_tiles()[-1].effect_name == "Comp"
    undo_cycle(window, before)


def test_replace_with_a_wide_effect_inserts_the_filler(window):
    window.replace_effect(6, DLXR)
    assert ids(window)[-2:] == [DLXR, WIDE_FILLER_ID]
    assert window.dsp_percent() > 0


def test_remove_effect_makes_an_empty_slot(window):
    before = window.current_patch
    window.remove_effect(1)
    assert ids(window)[:3] == [0x1000080, 0, 0x500002A]
    assert [t.is_empty for t in window.chain_tiles()][:3] == [False, True, False]
    undo_cycle(window, before)


def test_reorder_effects_by_move(window):
    before = window.current_patch
    window.move_effect(6, 0)
    assert window.chain_tiles()[0].effect_name == "Hall"
    undo_cycle(window, before)


def test_effects_not_on_the_a1_four_are_refused(qtbot, catalog, tmp_path):
    w = MainWindow(catalog, a1_ids={0x1000010}, backup_dir=tmp_path)
    qtbot.addWidget(w)
    w.load_offline(BACKUP)
    w.select_location(44)
    errors = []
    w.error_shown.connect(errors.append)
    w.replace_effect(6, DLXR)
    assert ids(w)[6] == HALL and not w.is_dirty(44) and errors
    w.replace_effect(6, COMP)
    assert ids(w)[6] == COMP


def test_catalog_double_click_replaces_the_selected_tile(window):
    window.select_tile(6)
    panel = window.catalog_panel
    panel.search.setText("Comp")
    panel.list.itemDoubleClicked.emit(panel.item_of("Comp"))
    assert window.current_patch.effects[6].effect_id == COMP


def test_double_click_without_selection_fills_the_first_empty_tile(window):
    window.remove_effect(6)
    window.chain.select(None)
    window.catalog_panel.search.setText("Comp")
    window.catalog_panel.list.itemDoubleClicked.emit(window.catalog_panel.item_of("Comp"))
    assert ids(window)[6] == COMP


def drop(tile, fmt, value):
    mime = QMimeData()
    mime.setData(fmt, str(value).encode())
    event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tile.dropEvent(event)


def test_drag_a_catalog_row_onto_a_tile_replaces_it(window):
    drop(window.chain_tiles()[0], MIME_EFFECT, COMP)
    assert window.current_patch.effects[0].effect_id == COMP


def test_drag_a_tile_onto_another_reorders(window):
    tiles = window.chain_tiles()
    drop(tiles[-1], MIME_SLOT, tiles[0].slot_index)  # OptComp dropped on Hall: moves to the end
    assert [t.effect_name for t in window.chain_tiles() if not t.is_empty][-1] == "OptComp"


def test_catalog_list_provides_drag_data(window):
    panel = window.catalog_panel
    mime = panel.list.mimeData([panel.item_of("Comp")])
    assert mime.hasFormat(MIME_EFFECT)
    assert int(bytes(mime.data(MIME_EFFECT))) in window.catalog


def test_empty_tiles_are_padded_and_droppable(window):
    window.remove_effect(6)
    assert len(window.chain_tiles()) >= 5 and window.chain_tiles()[-1].is_empty
    drop(window.chain_tiles()[-1], MIME_EFFECT, COMP)
    assert COMP in ids(window)


def test_dsp_meter_blocks_save_above_100(qtbot, catalog, tmp_path):
    t = fake_pedal([B1] * 43 + [HB_BYTES])
    w = MainWindow(catalog, a1_ids=None, transport_factory=lambda: t, backup_dir=tmp_path)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    w.select_location(44)
    assert not w.save_button.isEnabled()  # clean
    w.rename_patch("Edit")
    assert w.save_button.isEnabled()
    assert 60 < w.dsp_percent() < 100 and w.dsp_bar.format().startswith("DSP")
    for slot, effect in ((6, DLXR), (0, DLXR)):  # three big amps push past 100 %
        w.replace_effect(slot, effect)
    assert w.dsp_percent() > 100
    assert not w.save_button.isEnabled() and "100" in w.save_button.toolTip()
    sent_before = len(t.sent)
    w.save_current_patch()
    assert len(t.sent) == sent_before
    w.undo()
    w.undo()
    assert w.save_button.isEnabled()
    w.close()


def connected(qtbot, catalog, tmp_path, transport=None, patches=None):
    t = fake_pedal(patches or [B1] * 43 + [HB_BYTES], transport=transport)
    w = MainWindow(catalog, a1_ids=None, transport_factory=lambda: t, backup_dir=tmp_path / "autosave",
                   pedal_timeout=0.3)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    qtbot.waitUntil(lambda: w.memory_bar.value() > 0, timeout=3000)
    w.select_location(44)
    return w, t


def wire(t):
    return [m.data for m in t.sent if isinstance(m, SysexMessage)]


class OrderCheckingTransport(FakeTransport):
    """Records whether the backup folder already had a file when the write was sent."""

    def __init__(self, folder):
        super().__init__()
        self.folder = folder
        self.backup_at_write = None

    def send(self, msg):
        if isinstance(msg, SysexMessage) and msg.data.startswith(HDR + b"\x45"):
            self.backup_at_write = sorted(self.folder.glob("*.zptc"))
        super().send(msg)


def test_save_sends_the_sent_form_in_order_and_backs_up_first(qtbot, catalog, tmp_path):
    t = OrderCheckingTransport(tmp_path / "autosave")
    w, t = connected(qtbot, catalog, tmp_path, transport=t)
    before = len(wire(t))
    w.set_param(1, 1, 60)
    w.rename_patch("Edited")
    expected = build_zptc(edit.sent_form(w.current_patch))
    readback = build_zptc(edit.with_fillers(parse_zptc(expected), catalog))
    queue_save(t, previous=HB_BYTES, readback=readback)
    with qtbot.waitSignal(w.save_finished, timeout=5000) as blocker:
        w.save_button.click()
    assert blocker.args == [True]
    m = 0x6E
    assert wire(t)[before:] == [
        sysex.pc_mode(True, m),
        sysex.read_patch_request(44, 10, m),
        sysex.write_patch_request(44, expected, 10, m),
        sysex.read_patch_request(44, 10, m),
        sysex.pc_mode(False, m),
    ]
    # the written buffer holds no 0x00000001 filler
    sent_patch = parse_zptc(expected)
    assert WIDE_FILLER_ID not in [s.effect_id for s in sent_patch.effects]
    backups = list((tmp_path / "autosave").glob("*.zptc"))
    assert backups == t.backup_at_write and len(backups) == 1
    assert backups[0].read_bytes()[:len(HB_BYTES)] == HB_BYTES[:len(HB_BYTES)]
    # success: clean, and the in-memory patch is the read-back
    assert not w.is_dirty(44) and not w.save_button.isEnabled()
    assert w.current_patch.name == "Edited"
    assert WIDE_FILLER_ID in ids(w)
    w.close()


def test_read_back_mismatch_keeps_the_patch_dirty_and_reports(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    w.rename_patch("Edited")
    queue_save(t, previous=HB_BYTES, readback=HB_BYTES)  # pedal kept the old content
    errors = []
    w.error_shown.connect(errors.append)
    with qtbot.waitSignal(w.save_finished, timeout=5000) as blocker:
        w.save_current_patch()
    assert blocker.args == [False]
    assert any(strings.ERR_READBACK_DIFFERS in e for e in errors)
    assert w.is_dirty(44) and w.current_patch.name == "Edited"
    assert wire(t)[-1] == sysex.pc_mode(False, 0x6E)
    w.close()


@pytest.mark.parametrize("answered_reads", [0, 1])
def test_timeout_during_save_reports_an_error_and_stays_dirty(qtbot, catalog, tmp_path, answered_reads):
    w, t = connected(qtbot, catalog, tmp_path)
    w.rename_patch("Edited")
    bank, slot = divmod(43, 10)
    for _ in range(answered_reads):  # 0: the first read times out; 1: the write is never acknowledged
        t.on(HDR + b"\x46", S(patch_reply(bank, slot, HB_BYTES)))
    errors = []
    w.error_shown.connect(errors.append)
    with qtbot.waitSignal(w.save_finished, timeout=5000) as blocker:
        w.save_current_patch()
    assert blocker.args == [False]
    assert errors and w.is_dirty(44)
    wrote = any(m.startswith(HDR + b"\x45") for m in wire(t))
    assert wrote == bool(answered_reads)  # no read-back, no write
    assert wire(t)[-1] == sysex.pc_mode(False, 0x6E)
    w.close()


def test_save_is_refused_without_a_backup_folder(qtbot, catalog):
    t = fake_pedal([B1] * 43 + [HB_BYTES])
    w = MainWindow(catalog, a1_ids=None, transport_factory=lambda: t, pedal_timeout=0.3)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    w.select_location(44)
    w.rename_patch("Edited")
    errors = []
    w.error_shown.connect(errors.append)
    w.save_current_patch()
    assert errors == [strings.ERR_NO_BACKUP_DIR]
    assert not any(m.startswith(HDR + b"\x45") for m in wire(t))
    w.close()


def test_save_and_open_single_files_round_trip(window, tmp_path):
    window.rename_patch("OnFile")
    window.set_param(1, 1, 61)
    target = tmp_path / "out.zptc"
    window.save_file(target)
    saved = parse_zptc(target.read_bytes())
    assert saved.name == "OnFile" and saved.effects[1].params[1] == 61
    window.select_location(1)
    window.open_file(target)
    assert window.current_patch.name == "OnFile" and window.is_dirty(1)
    assert window.current_patch.effects[1].params[1] == 61
    window.undo()
    assert window.current_patch.name != "OnFile" and not window.is_dirty(1)


def test_open_file_reports_a_bad_file(window, tmp_path):
    bad = tmp_path / "bad.zptc"
    bad.write_bytes(b"nope")
    errors = []
    window.error_shown.connect(errors.append)
    window.open_file(bad)
    assert errors and not window.is_dirty(44)


def answer(monkeypatch, button, calls):
    def fake(*args, **kwargs):
        calls.append(args)
        return button == QMessageBox.StandardButton.Discard

    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(fake))


def test_reload_asks_before_discarding_edits(window, monkeypatch):
    window.rename_patch("Edited")
    calls = []
    answer(monkeypatch, QMessageBox.StandardButton.Cancel, calls)
    window.reload()
    assert calls and window.is_dirty(44) and window.current_patch.name == "Edited"
    answer(monkeypatch, QMessageBox.StandardButton.Discard, calls)
    window.reload()
    assert not window.is_dirty(44)


def test_reload_does_not_ask_when_clean(window, monkeypatch):
    calls = []
    answer(monkeypatch, QMessageBox.StandardButton.Cancel, calls)
    window.reload()
    assert not calls


def test_closing_a_dirty_window_asks(window, monkeypatch):
    window.rename_patch("Edited")
    calls = []
    answer(monkeypatch, QMessageBox.StandardButton.Cancel, calls)
    assert window.close() is False and calls
    answer(monkeypatch, QMessageBox.StandardButton.Discard, calls)
    assert window.close() is True


def test_switching_patches_keeps_edits_without_asking(window, monkeypatch):
    calls = []
    answer(monkeypatch, QMessageBox.StandardButton.Cancel, calls)
    window.rename_patch("Edited")
    window.select_location(1)
    window.select_location(44)
    assert window.current_patch.name == "Edited" and not calls
    window.undo()  # the undo stack belongs to the patch, so it is still there
    assert window.current_patch.name == "HB Jazz"


def test_undo_redo_actions_have_the_standard_shortcuts(window):
    assert window.undo_action.shortcut().toString() == "Ctrl+Z"
    assert "Ctrl+Shift+Z" in [s.toString() for s in window.redo_action.shortcuts()]
    window.rename_patch("Edited")
    assert window.undo_action.isEnabled()
    window.undo_action.trigger()
    assert window.current_patch.name == "HB Jazz" and window.redo_action.isEnabled()


# ------------------------------------------------------------------ live edit

def test_live_edit_is_off_by_default_and_sends_nothing(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    assert not w.live_check.isChecked()
    before = len(t.sent)
    w.select_tile(1)
    w.param_rows()[1].spin.setValue(50)
    w.chain_tiles()[0].power.click()
    assert len(t.sent) == before
    w.close()


def test_live_edit_sends_param_and_on_off_when_enabled(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    w.live_check.setChecked(True)
    qtbot.waitUntil(lambda: len(t.sent) > 0 and t.sent[-1].__class__.__name__ == "ProgramChange", timeout=3000)
    w.select_tile(1)
    w.param_rows()[1].spin.setValue(50)  # dial index 1 -> param 3 of slot 1
    w.chain_tiles()[0].power.click()
    qtbot.waitUntil(lambda: sysex.set_param(0, 0, 0, 0x6E) in wire(t), timeout=3000)
    sent = wire(t)
    assert sysex.set_param(1, 3, 50, 0x6E) in sent
    assert sysex.set_param(0, 0, 0, 0x6E) in sent  # slot 0 switched off
    w.close()


def test_live_slot_mapping_is_isolated():
    from zoomstudio.ui.main_window import live_message

    # verified on a real A1 FOUR (2026-11-24): the slot is the index in the chain with fillers
    patch = parse_zptc(HB_BYTES)
    assert live_message(patch, 4, 2, 50) == (4, 4, 50)  # dial 2 is parameter 4 (0 = on/off, 1 reserved)
    assert live_message(patch, 4, None, 0) == (4, 0, 0)  # on/off is parameter 0


def test_effect_and_parameter_texts_are_shown_in_spanish(window):
    from zoomstudio.effects import i18n

    window.chain.select(1)  # FD DLXR in HB Jazz
    info = window.catalog[DLXR]
    assert window.params.description.text() == i18n.effect_description(info)
    assert window.params.description.text().startswith("Modela el sonido del Fender '65 Deluxe Reverb")
    assert window.params.help.text() == i18n.param_explanation(info.params[0])
    assert window.params.help.text() != info.params[0].explanation


def test_catalog_detail_is_shown_in_spanish(window):
    from zoomstudio.effects import i18n

    panel = window.catalog_panel
    panel.list.setCurrentRow(panel.row_of("Comp"))
    info = next(i for i in window.catalog.values() if i.name == panel.detail_name.text())
    assert panel.detail.text() == i18n.effect_description(info)
