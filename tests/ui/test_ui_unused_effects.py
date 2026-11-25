"""«Sin uso»: find the installed effects no patch uses, and free their space in one confirmed go.

Same setup as the effects manager tests: in-memory pedal files behind a scripted FakeTransport. The pedal holds one
patch (001: it uses OptComp), so Comp, FD DLXR, FD-DX1x12, Gt GEQ 7 and Hall are installed and unused.
"""
import pytest
from PySide6.QtCore import Qt

import test_ui_effects_manager as manager
from test_ui_effects_manager import BEFORE, PATCHES, PedalFiles, connected_window, entry_item, names, open_screen
from ui_replies import FIXTURES
from zoomstudio.device import PedalClient
from zoomstudio.device.errors import PedalError
from zoomstudio.effects import flst
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import strings as ST
from zoomstudio.ui.dialogs import ConfirmDialog
from zoomstudio.ui.effects_manager import ROLE_UNUSED

from fixture_files import EFFECTS  # noqa: E402
UNUSED = ["FDDLXR1U.ZD2", "FDDX1X12.ZD2", "HALL.ZD2", "GTGEQ71U.ZD2", "COMP.ZD2"]  # by file size, largest first
SIZES = {"FDDLXR1U.ZD2": 44154, "FDDX1X12.ZD2": 32994, "HALL.ZD2": 17933, "GTGEQ71U.ZD2": 17772, "COMP.ZD2": 13390}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


def make(qtbot, monkeypatch, catalog, tmp_path, files=None, bank=0, **kw):
    monkeypatch.setattr(manager, "PATCHES", PATCHES[:1])  # only 001: it uses OptComp
    files = files or PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files, **kw)
    for i in range(bank):  # bank patches that use the effects of HB Jazz
        w.bank_store.add((FIXTURES / "53-HB-Jazz.zptc").read_bytes(), origin=2, now=f"2026112{i}-101500")
    return w, open_screen(qtbot, w), files


def marked(panel):
    return sorted(f for f in names(panel, "installed") if entry_item(panel, "installed", f).data(ROLE_UNUSED))


def show_unused(panel):
    panel.group_combo.setCurrentIndex(panel.group_combo.findData(ST.UNUSED_KEY))


def asks(monkeypatch, answer=True):
    seen = []
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda parent, title, text, *a, **k: seen.append((title, text)) or answer))
    return seen


# ------------------------------------------------------------------- the marker

def test_only_unused_installed_effects_carry_the_marker(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = make(qtbot, monkeypatch, catalog, tmp_path)
    assert marked(panel) == sorted(UNUSED)  # OptComp is in patch 1
    item = entry_item(panel, "installed", "HALL.ZD2")
    assert item.data(ROLE_UNUSED) == ST.UNUSED_TIP and ST.UNUSED_TIP in item.toolTip()
    assert ST.UNUSED in item.data(Qt.ItemDataRole.AccessibleTextRole) and ST.UNUSED == "Sin uso"
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData("all"))
    assert not any(entry_item(panel, "available", f).data(ROLE_UNUSED) for f in names(panel, "available"))


def test_no_marker_while_usage_is_not_confirmed(qtbot, monkeypatch, catalog, tmp_path):
    w, panel, _files = make(qtbot, monkeypatch, catalog, tmp_path)
    w.select_location(1)
    w.rename_patch("Otro")  # an unsaved edit: what the patches use is not settled
    w._refresh_effects_context()
    assert marked(panel) == [] and panel.unused_link.isHidden()
    show_unused(panel)
    assert names(panel, "installed") == [] and panel.unused_summary.text() == ST.UNUSED_UNKNOWN
    assert not panel.remove_selected_button.isEnabled()


def test_bank_patches_do_not_make_an_effect_in_use_but_the_tooltip_and_confirmation_say_so(qtbot, monkeypatch, catalog, tmp_path):
    seen = asks(monkeypatch)
    _w, panel, _files = make(qtbot, monkeypatch, catalog, tmp_path, bank=2)
    item = entry_item(panel, "installed", "HALL.ZD2")
    assert item.data(ROLE_UNUSED) and ST.unused_bank_note(2) == "Lo usan 2 patches del banco"
    assert ST.unused_bank_note(2) in item.toolTip()
    assert ST.unused_bank_note(1) == "Lo usa 1 patch del banco"
    panel.select_effect("HALL.ZD2")
    panel.remove_button.click()
    qtbot.waitUntil(lambda: "HALL.ZD2" not in names(panel, "installed"), timeout=5000)
    assert ST.unused_bank_note(2) in seen[0][1]  # the single removal repeats the line


# -------------------------------------------------------------------- the view

def test_the_filter_lists_unused_effects_by_size_with_a_summary(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = make(qtbot, monkeypatch, catalog, tmp_path)
    total = sum(SIZES.values())
    assert panel.unused_link.text() == ST.unused_summary(5, total) and not panel.unused_link.isHidden()
    assert ST.unused_summary(5, total).startswith("5 efectos sin uso · ") and "que se pueden liberar" in ST.unused_summary(5, total)
    panel.unused_link.click()  # the link applies the filter
    assert panel.group_combo.currentData() == ST.UNUSED_KEY
    assert panel.installed_names() == UNUSED  # largest first, across groups (the order the list shows)
    assert panel.unused_summary.text() == ST.unused_summary(5, total) and not panel.unused_summary.isHidden()
    assert names(panel, "available") == []
    panel.search.setText("hall")
    assert names(panel, "installed") == ["HALL.ZD2"]
    assert panel.unused_summary.text() == ST.unused_summary(1, SIZES["HALL.ZD2"])


# ------------------------------------------------------------------- free space

def tick(panel, *files):
    for f in files:
        assert panel.set_checked(f, True)


def test_effects_in_use_cannot_be_selected(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = make(qtbot, monkeypatch, catalog, tmp_path)
    show_unused(panel)
    assert panel.set_checked("OPTCOMP.ZD2", True) is False and panel.checked_names() == []
    assert entry_item(panel, "installed", "HALL.ZD2").data(ROLE_UNUSED)
    tick(panel, "HALL.ZD2")
    assert panel.checked_names() == ["HALL.ZD2"]
    panel.select_all_button.click()
    assert sorted(panel.checked_names()) == sorted(UNUSED)
    panel.select_all_button.click()  # again: none
    assert panel.checked_names() == []


def test_three_effects_are_removed_in_sequence_after_one_confirmation(qtbot, monkeypatch, catalog, tmp_path):
    seen = asks(monkeypatch)
    _w, panel, files = make(qtbot, monkeypatch, catalog, tmp_path, bank=1)
    refreshed = []
    panel.state_shown.connect(lambda: refreshed.append(1))
    show_unused(panel)
    tick(panel, "FDDLXR1U.ZD2", "HALL.ZD2", "COMP.ZD2")
    freed = SIZES["FDDLXR1U.ZD2"] + SIZES["HALL.ZD2"] + SIZES["COMP.ZD2"]
    assert panel.remove_selected_button.text() == ST.remove_selected(3, freed)
    assert panel.remove_selected_button.isEnabled()
    panel.remove_selected_button.click()
    qtbot.waitUntil(lambda: not {"FDDLXR1U.ZD2", "HALL.ZD2", "COMP.ZD2"} & set(names(panel, "installed")), timeout=8000)
    assert len(seen) == 1  # ONE confirmation
    text = seen[0][1]
    assert all(n in text for n in ("FD DLXR", "Hall", "Comp")) and ST.effects_size(freed) in text
    assert ST.unused_bank_note(1) in text and ST.EFFECTS_BACKUP_NOTE in text
    installed = flst.installed_names(files.files[flst.FLST_NAME])
    assert all(f not in installed and f not in files.files for f in ("FDDLXR1U.ZD2", "HALL.ZD2", "COMP.ZD2"))
    assert "FDDX1X12.ZD2" in installed and "OPTCOMP.ZD2" in files.files  # the others stay
    assert len(list((tmp_path / "effects").glob("*FLST_SEQ.ZT2"))) == 3  # a backup per call
    assert len(refreshed) >= 3  # the state is read again after each one
    assert panel.checked_names() == []


def test_it_stops_at_the_first_failure_and_says_what_was_and_was_not_removed(qtbot, monkeypatch, catalog, tmp_path):
    asks(monkeypatch)

    class Failing(PedalFiles):
        def install(self, mp):
            super().install(mp)
            real = PedalClient.delete_file

            def delete_file(client, name, timeout=None):
                if name == "FDDX1X12.ZD2":
                    raise PedalError("boom")
                return real(client, name, timeout)

            mp.setattr(PedalClient, "delete_file", delete_file)

    w, panel, files = make(qtbot, monkeypatch, catalog, tmp_path, files=Failing(BEFORE))
    errors = []
    w.error_shown.connect(errors.append)
    show_unused(panel)
    tick(panel, "FDDLXR1U.ZD2", "FDDX1X12.ZD2", "HALL.ZD2")
    panel.remove_selected_button.click()
    qtbot.waitUntil(lambda: any(ST.REMOVE_MANY_STOPPED in e for e in errors), timeout=8000)
    report = errors[-1]
    assert "FD DLXR" in report.split(ST.REMOVE_NOT_REMOVED)[0] and "HALL" not in report.split(ST.REMOVE_NOT_REMOVED)[0]
    assert "FD-DX1x12" in report.split(ST.REMOVE_NOT_REMOVED)[1] and "Hall" in report.split(ST.REMOVE_NOT_REMOVED)[1]
    assert "FDDLXR1U.ZD2" not in files.files and "HALL.ZD2" in files.files  # it did not go on to the third
    assert flst.is_installed(files.files[flst.FLST_NAME], "HALL.ZD2")


def test_a_declined_confirmation_writes_nothing(qtbot, monkeypatch, catalog, tmp_path):
    seen = asks(monkeypatch, answer=False)
    _w, panel, files = make(qtbot, monkeypatch, catalog, tmp_path)
    show_unused(panel)
    tick(panel, "HALL.ZD2", "COMP.ZD2")
    panel.remove_selected_button.click()
    qtbot.wait(200)
    assert len(seen) == 1 and files.files[flst.FLST_NAME] == BEFORE and "HALL.ZD2" in files.files
    assert not list((tmp_path / "effects").glob("*"))  # no backup either


def test_a_read_only_pedal_blocks_the_selection_removal(qtbot, monkeypatch, catalog, tmp_path):
    seen = asks(monkeypatch)
    w, panel, files = make(qtbot, monkeypatch, catalog, tmp_path, member=0x0C)
    show_unused(panel)
    tick(panel, "HALL.ZD2")
    assert not panel.remove_selected_button.isEnabled()
    errors = []
    w.error_shown.connect(errors.append)
    w._on_effects_remove_many(["HALL.ZD2"])
    qtbot.wait(150)
    assert errors == [w.write_block_reason()] and not seen
    assert files.files[flst.FLST_NAME] == BEFORE and "HALL.ZD2" in files.files


def unused_view(qtbot, monkeypatch, catalog, tmp_path):
    """The state the audits look at: the «Sin uso» view with two effects ticked and a bank patch using them."""
    w, panel, _files = make(qtbot, monkeypatch, catalog, tmp_path, bank=1)
    show_unused(panel)
    tick(panel, "HALL.ZD2", "COMP.ZD2")
    return w
