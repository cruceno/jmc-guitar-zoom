"""Librarian: backup all, copy/paste/swap/clear, export/import, A1/A2/A3 save blockers."""
import json
import pytest
from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from zoomstudio.ui import strings
from zoomstudio.ui.dialogs import ConfirmDialog

from ui_replies import FIXTURES, HDR, S, fake_pedal, patch_reply
from zoomstudio.device import sysex
from zoomstudio.device.messages import SysexMessage
from zoomstudio.device.transport import FakeTransport
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.patches import edit
from zoomstudio.patches.library import empty_patch
from zoomstudio.patches.model import EffectSlot
from zoomstudio.patches.zptc import build_zptc, parse_zptc
from zoomstudio.ui.main_window import MainWindow
from zoomstudio.ui.widgets import MIME_PATCH

BACKUP = FIXTURES / "backup"
HB = (FIXTURES / "53-HB-Jazz.zptc").read_bytes()
B1 = (BACKUP / "001.zptc").read_bytes()
GEQ, HALL = 0x2000054, 0x9000030
M = 0x6E


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"))


def hb(name: str) -> bytes:
    return build_zptc(edit.rename(parse_zptc(HB), name))


HB_ONE, HB_TWO = hb("HB One"), hb("HB Two")


@pytest.fixture(autouse=True)
def _close_windows():
    """Close every window a test made (stops its worker thread) even when a test fails."""
    yield
    while _WINDOWS:
        w = _WINDOWS.pop()
        w.confirm_discard = lambda action: True
        w.close()


@pytest.fixture
def yes(monkeypatch):
    """Answer every confirmation with Yes and record the texts asked."""
    asked = []

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return True

    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(question))
    return asked


def wire(t):
    return [m.data for m in t.sent if isinstance(m, SysexMessage)]


def connected(qtbot, catalog, tmp_path, patches=None, a1_ids=None, timeout=0.3):
    patches = patches or PEDAL
    t = fake_pedal(patches)
    w = MainWindow(catalog, a1_ids=a1_ids, transport_factory=lambda: t, backup_dir=tmp_path / "autosave",
                   library_dir=tmp_path / "patches", pedal_timeout=timeout)
    qtbot.addWidget(w)
    _WINDOWS.append(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    qtbot.waitUntil(lambda: w.memory_bar.value() > 0, timeout=3000)
    return w, t


def queue_reads(t, patches):
    """Replies for a second full read (the one made while connecting used up the first set)."""
    for loc, raw in enumerate(patches, start=1):
        bank, slot = divmod(loc - 1, 10)
        t.on(HDR + b"\x46", S(patch_reply(bank, slot, raw)))


_WINDOWS = []
PEDAL = [B1] * 42 + [HB_ONE, HB_TWO] + [B1] * 6


def queue_write(t, loc, previous, readback):
    bank, slot = divmod(loc - 1, 10)
    t.on(HDR + b"\x46", S(patch_reply(bank, slot, previous)))
    t.on(HDR + b"\x45", S(HDR + b"\x00\x00"))
    t.on(HDR + b"\x46", S(patch_reply(bank, slot, readback)))


def echo(raw: bytes, catalog) -> bytes:
    """What the pedal reads back for a buffer it accepted: the chain with wide fillers."""
    return build_zptc(edit.with_fillers(parse_zptc(raw), catalog))


def sent(raw: bytes) -> bytes:
    return build_zptc(edit.sent_form(parse_zptc(raw)))


# ------------------------------------------------------------------ backup all

def test_backup_all_writes_50_patches_and_a_manifest(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    queue_reads(t, PEDAL)
    before = len(wire(t))
    with qtbot.waitSignal(w.backup_finished, timeout=8000) as blocker:
        w.backup_all(with_files=False, stamp="20260101-120000")
    folder = tmp_path / "patches" / "backup-20260101-120000"
    assert blocker.args == [str(folder), True]
    files = sorted(p.name for p in folder.glob("*.zptc"))
    assert files == [f"{n:03d}.zptc" for n in range(1, 51)]
    assert (folder / "044.zptc").read_bytes() == PEDAL[43]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["patch_count"] == 50 and manifest["model_id"] == "0x6E"
    assert [e["status"] for e in manifest["patches"]] == ["ok"] * 50
    assert manifest["patches"][43] == {"location": 44, "file": "044.zptc", "bytes": len(PEDAL[43]), "status": "ok"}
    # read-only on the wire: PC mode around 50 reads, never a write
    assert wire(t)[before:] == ([sysex.pc_mode(True, M)]
                                + [sysex.read_patch_request(n, 10, M) for n in range(1, 51)]
                                + [sysex.pc_mode(False, M)])


def test_backup_all_refuses_an_existing_folder(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    existing = tmp_path / "patches" / "backup-20260101-120000"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("mine")
    before, errors = len(wire(t)), []
    w.error_shown.connect(errors.append)
    with qtbot.waitSignal(w.backup_finished, timeout=5000) as blocker:
        w.backup_all(with_files=False, stamp="20260101-120000")
    assert blocker.args[1] is False
    assert errors and "ya existe" in errors[0]
    assert [p.name for p in existing.iterdir()] == ["keep.txt"]
    assert len(wire(t)) == before  # nothing was asked of the pedal


def test_backup_all_can_include_the_pedal_files(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    queue_reads(t, PEDAL)
    client = w._worker._client
    client.list_files = lambda *a, **k: ["FLST_SEQ.ZT2", "HALL.ZD2"]
    client.read_file = lambda name, *a, **k: b"data of " + name.encode()
    with qtbot.waitSignal(w.backup_finished, timeout=8000):
        w.backup_all(with_files=True, stamp="20260101-120001")
    files = tmp_path / "patches" / "pedal-files-20260101-120001"
    assert sorted(p.name for p in files.iterdir()) == ["FLST_SEQ.ZT2", "HALL.ZD2"]
    assert (files / "HALL.ZD2").read_bytes() == b"data of HALL.ZD2"
    assert len(list((tmp_path / "patches" / "backup-20260101-120001").glob("*.zptc"))) == 50


def test_backup_all_can_be_cancelled(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    queue_reads(t, PEDAL)
    w._worker.backup_progress.connect(lambda phase, done, total: w._worker.cancel() if done == 5 else None,
                                      Qt.ConnectionType.DirectConnection)
    with qtbot.waitSignal(w.backup_finished, timeout=8000) as blocker:
        w.backup_all(with_files=False, stamp="20260101-120002")
    folder = tmp_path / "patches" / "backup-20260101-120002"
    assert blocker.args[1] is False
    assert len(list(folder.glob("*.zptc"))) == 5
    assert json.loads((folder / "manifest.json").read_text())["cancelled"] is True


# ------------------------------------------------------------- pedal operations

def test_swap_writes_both_slots_in_order_through_the_safe_path(qtbot, catalog, tmp_path, yes):
    w, t = connected(qtbot, catalog, tmp_path)
    before = len(wire(t))
    queue_write(t, 43, HB_ONE, echo(HB_TWO, catalog))
    queue_write(t, 44, HB_TWO, echo(HB_ONE, catalog))
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.swap_patches(43, 44)
    assert "52" in yes[0] and "53" in yes[0]  # display numbers of both slots
    assert blocker.args == [[43, 44], 0]
    assert wire(t)[before:] == [
        sysex.pc_mode(True, M),
        sysex.read_patch_request(43, 10, M), sysex.write_patch_request(43, sent(HB_TWO), 10, M),
        sysex.read_patch_request(43, 10, M),
        sysex.read_patch_request(44, 10, M), sysex.write_patch_request(44, sent(HB_ONE), 10, M),
        sysex.read_patch_request(44, 10, M),
        sysex.pc_mode(False, M),
    ]
    backups = sorted((tmp_path / "autosave").glob("*.zptc"))
    assert [b.name[:3] for b in backups] == ["043", "044"]
    assert backups[0].read_bytes() == HB_ONE and backups[1].read_bytes() == HB_TWO
    assert w._patches[43].name == "HB Two" and w._patches[44].name == "HB One"
    assert not w.is_dirty(43) and not w.is_dirty(44)


def test_swap_stops_after_a_failed_first_write_and_leaves_the_second_untouched(qtbot, catalog, tmp_path, yes):
    w, t = connected(qtbot, catalog, tmp_path)
    before = len(wire(t))
    bank, slot = divmod(42, 10)
    t.on(HDR + b"\x46", S(patch_reply(bank, slot, HB_ONE)))  # backup read works, the write is never acked
    errors = []
    w.error_shown.connect(errors.append)
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.swap_patches(43, 44)
    assert blocker.args == [[], 43]
    assert errors and "52" in errors[0] and "detenida" in errors[0]
    ops = wire(t)[before:]
    assert sum(d.startswith(HDR + b"\x45") for d in ops) == 1  # only slot 43 was attempted
    assert sysex.read_patch_request(44, 10, M) not in ops
    assert ops[-1] == sysex.pc_mode(False, M)
    assert [b.name[:3] for b in (tmp_path / "autosave").glob("*.zptc")] == ["043"]
    assert w._patches[44].name == "HB Two" and w._patches[43].name == "HB One"


def test_clear_writes_the_factory_empty_patch(qtbot, catalog, tmp_path, yes):
    w, t = connected(qtbot, catalog, tmp_path)
    before = len(wire(t))
    empty = sent(build_zptc(empty_patch()))
    queue_write(t, 44, HB_TWO, empty)
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.clear_slot(44)
    assert blocker.args == [[44], 0]
    assert wire(t)[before:] == [
        sysex.pc_mode(True, M), sysex.read_patch_request(44, 10, M),
        sysex.write_patch_request(44, empty, 10, M), sysex.read_patch_request(44, 10, M),
        sysex.pc_mode(False, M),
    ]
    assert w._patches[44].name == "Empty" and not w.is_dirty(44)


def test_write_all_dirty_sends_each_dirty_slot_through_the_safe_path(qtbot, catalog, tmp_path, yes):
    w, t = connected(qtbot, catalog, tmp_path)
    w.select_location(43)
    w.rename_patch("Edit A")
    w.select_location(44)
    w.rename_patch("Edit B")
    before = len(wire(t))
    a, b = sent(build_zptc(w._patches[43])), sent(build_zptc(w._patches[44]))
    queue_write(t, 43, HB_ONE, echo(a, catalog))
    queue_write(t, 44, HB_TWO, echo(b, catalog))
    with qtbot.waitSignal(w.queue_finished, timeout=5000) as blocker:
        w.write_all_dirty()
    assert blocker.args == [[43, 44], 0]
    ops = wire(t)[before:]
    assert [d for d in ops if d.startswith(HDR + b"\x45")] == [
        sysex.write_patch_request(43, a, 10, M), sysex.write_patch_request(44, b, 10, M)]
    assert not w.any_dirty()


# ------------------------------------------------------------- save blockers

def test_import_folder_with_a_non_a1_effect_blocks_save_with_the_reason(qtbot, catalog, tmp_path, yes):
    allowed = {0x1000080, 0x400002C, 0x500002A, GEQ}  # Hall is not runnable on the A1 FOUR
    w, t = connected(qtbot, catalog, tmp_path, a1_ids=allowed)
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "044.zptc").write_bytes(HB)
    before, errors = len(wire(t)), []
    w.error_shown.connect(errors.append)
    w.import_folder(folder)
    w.select_location(44)
    assert any("Hall" in e and edit.NOT_RUNNABLE_REASON in e for e in errors)
    assert not any(d.startswith(HDR + b"\x45") for d in wire(t)[before:])  # nothing written
    assert w.is_dirty(44) and w._patches[44].name == "HB Jazz"
    hall = [x for x in w.chain_tiles() if x.effect_name == "Hall"][0]
    assert hall.problem == edit.NOT_RUNNABLE_REASON
    assert not w.save_button.isEnabled() and "Hall" in w.save_button.toolTip()
    w.save_current_patch()
    assert not any(d.startswith(HDR + b"\x45") for d in wire(t)[before:])


def test_unknown_effect_blocks_save(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    w.select_location(1)  # backup 001 holds effects that are not in the fixture catalog
    w.rename_patch("Edited")
    assert w.is_dirty(1) and not w.save_button.isEnabled()
    assert edit.UNKNOWN_EFFECT_REASON in w.save_button.toolTip()
    assert any(x.problem == edit.UNKNOWN_EFFECT_REASON for x in w.chain_tiles())
    before, errors = len(wire(t)), []
    w.error_shown.connect(errors.append)
    w.save_current_patch()
    assert errors and edit.UNKNOWN_EFFECT_REASON in errors[0]
    assert len(wire(t)) == before


def test_chain_beyond_the_slot_cap_blocks_save_before_any_write(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    w.select_location(44)
    patch = parse_zptc(HB)
    patch.effects = [EffectSlot(effect_id=GEQ, params=[24] * 12) for _ in range(9)]  # 9 wide = 18 slots
    path = tmp_path / "nine-geq.zptc"
    path.write_bytes(build_zptc(patch))
    w.open_file(path)
    assert w.is_dirty(44) and not w.save_button.isEnabled()
    assert "slots" in w.save_button.toolTip()
    before, errors = len(wire(t)), []
    w.error_shown.connect(errors.append)
    w.save_current_patch()
    assert errors and "slots" in errors[0]
    assert len(wire(t)) == before


def test_opening_a_file_with_a_non_a1_effect_flags_the_tile(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path, a1_ids={0x1000080, 0x400002C, 0x500002A, GEQ})
    w.select_location(44)
    path = tmp_path / "hb.zptc"
    path.write_bytes(HB)
    w.open_file(path)
    flagged = [x.effect_name for x in w.chain_tiles() if x.problem]
    assert flagged == ["Hall"]
    assert not w.save_button.isEnabled()


# ------------------------------------------------------------ offline operations

@pytest.fixture
def offline(qtbot, catalog, tmp_path):
    t = FakeTransport()
    w = MainWindow(catalog, a1_ids=None, transport_factory=lambda: t, backup_dir=tmp_path / "autosave",
                   library_dir=tmp_path / "patches")
    qtbot.addWidget(w)
    _WINDOWS.append(w)
    w.load_offline(BACKUP)
    return w, t


def test_offline_copy_paste_swap_clear_mark_dirty_without_sending(offline, yes):
    w, t = offline
    w.copy_patch(44)
    w.paste_patch(45)
    assert w._patches[45].name == "HB Jazz" and w.is_dirty(45)
    names = (w._patches[1].name, w._patches[2].name)
    w.swap_patches(1, 2)
    assert (w._patches[1].name, w._patches[2].name) == names[::-1]
    assert w.is_dirty(1) and w.is_dirty(2)
    w.clear_slot(44)
    assert w._patches[44].name == "Empty" and w.is_dirty(44)
    assert t.sent == []
    w.select_location(44)
    w.undo()
    assert w._patches[44].name == "HB Jazz" and not w.is_dirty(44)


def test_declining_the_swap_changes_nothing(offline, monkeypatch):
    w, t = offline
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda *a, **k: False))
    w.swap_patches(1, 2)
    assert w._patches[1].name == "Acoustic A" and not w.any_dirty()


def test_dragging_a_patch_onto_another_confirms_and_swaps(offline, yes):
    w, t = offline
    item = w.patch_list.item(1)  # location 2
    mime = QMimeData()
    mime.setData(MIME_PATCH, QByteArray(b"1"))
    pos = QPointF(w.patch_list.visualItemRect(item).center())
    event = QDropEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w.patch_list.dropEvent(event)
    assert "19" not in yes[0] and "10" in yes[0] and "11" in yes[0]  # display numbers of slots 1 and 2
    assert w._patches[1].name == "Acoustic B" and w._patches[2].name == "Acoustic A"


def test_pasting_without_a_copy_reports_it(offline):
    w, _ = offline
    errors = []
    w.error_shown.connect(errors.append)
    w.paste_patch(5)
    assert errors == [strings.ERR_NOTHING_TO_PASTE] and not w.any_dirty()


def test_export_selected_and_all_then_import_back(offline, tmp_path, yes):
    w, _ = offline
    dest = tmp_path / "out"
    dest.mkdir()
    w.export_selected(dest, 44)
    assert [p.name for p in dest.glob("*.zptc")] == ["044-HB Jazz.zptc"]
    errors = []
    w.error_shown.connect(errors.append)
    w.export_selected(dest, 44)  # same file again: refused, not overwritten
    assert errors and "ya existe" in errors[0].lower()
    folder = w.export_all(dest)
    assert sorted(p.name for p in folder.glob("*.zptc")) == ["001.zptc", "002.zptc", "003.zptc", "044.zptc"]
    assert json.loads((folder / "manifest.json").read_text())["patches"][3]["location"] == 44
    w.clear_slot(44)
    w.import_folder(folder)
    assert w._patches[44].name == "HB Jazz" and w._patches[1].name == "Acoustic A"
    w.select_location(50)
    w.import_file(dest / next(p.name for p in dest.glob("*.zptc")))
    assert w._patches[50].name == "HB Jazz" and w.is_dirty(50)
