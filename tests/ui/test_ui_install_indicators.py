"""S6 of patch-bank-live-control: on-pedal / in-chain icons, a warning for effects the pedal lacks, Live blocks and
the quick install from the editor.

Everything goes through the window with an in-memory pedal file system (``PedalFiles``) behind a scripted
FakeTransport: the install runs the real worker slot and ``installer.install_effect``. No MIDI hardware is touched.
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from test_ui_effects_manager import AFTER, BEFORE, ON_PEDAL, PedalFiles, connected_window
from test_ui_editor import drop
from ui_replies import FIXTURES
from zoomstudio.effects import flst
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import strings as ST
from zoomstudio.ui.cards import ROLE_EFFECT, badge_rects, card_badges
from zoomstudio.ui.dialogs import ConfirmDialog
from zoomstudio.ui.main_window import MainWindow
from zoomstudio.ui.mime import MIME_EFFECT

REAL_READ = MainWindow._load_installed_state  # the conftest stubs it out for every other module


@pytest.fixture(autouse=True)
def reads_the_effect_list(monkeypatch):
    monkeypatch.setattr(MainWindow, "_load_installed_state", REAL_READ)


HALL, OPTCOMP, COMP, STRINGS = 0x9000030, 0x1000080, 0x1000010, 0x14400190  # STRINGS: 12Strings, installable
from fixture_files import EFFECTS  # noqa: E402


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


def ready(qtbot, w, effect=HALL):
    """Wait for the editor's own read of the pedal's effect list (it runs after the patches are read)."""
    qtbot.waitUntil(lambda: w.effect_installed(effect) is not None, timeout=5000)


@pytest.fixture
def ed(qtbot, monkeypatch, catalog, tmp_path):
    files = PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files)
    ready(qtbot, w)
    w.select_location(2)  # HB Jazz: OptComp, FD DLXR, FD-DX1x12, Gt GEQ 7 and Hall, all installed
    return w, files


def show_not_installed(qtbot, w):
    """The state the audits look at: Live on, 12Strings (not installed) in the chain with its warning, and the
    catalog card of 12Strings selected so the target card offers «Instalar en la pedalera»."""
    w._request_effects_state()  # the audits' windows read nothing by themselves
    qtbot.waitUntil(lambda: w.effect_installed(HALL) is not None, timeout=5000)
    w.select_location(2)
    w.replace_effect(0, STRINGS)
    w.live_check.setChecked(True)
    w.catalog_panel.search.setText("12Strings")
    w.catalog_panel.list.setCurrentItem(w.catalog_panel.item_of("12Strings"))


def asks(monkeypatch, answer=True):
    """Record every install-related confirmation (title, text) and answer it. The discard question that closing a
    dirty window asks is not one of them: it always agrees, so the window can close at the end of the test."""
    seen = []

    def ask(parent, title, text, *a, **k):
        if title == ST.DISCARD_TITLE:
            return True
        seen.append((title, text))
        return answer

    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(ask))
    return seen


def keys(panel, name):
    panel.search.setText(name)
    return [b.key for b in card_badges(panel.item_of(name).data(ROLE_EFFECT))]


def tile(w, slot):
    return next(t for t in w.chain.tiles() if t.slot_index == slot)


def effect_ids(w):
    return [s.effect_id for s in w.current_patch.effects]


def card_tooltip(panel, name, index):
    """The tooltip the real viewport shows over the ``index``-th icon of the card of ``name``."""
    panel.search.setText(name)
    item = panel.item_of(name)
    panel.list.scrollToItem(item)
    rects = badge_rects(panel.list.visualItemRect(item), len(card_badges(item.data(ROLE_EFFECT))))
    pos = rects[index].center().toPoint()
    QToolTip.hideText()
    QApplication.sendEvent(panel.list.viewport(), QHelpEvent(QEvent.Type.ToolTip, pos, panel.list.viewport().mapToGlobal(pos)))
    return QToolTip.text()


# ------------------------------------------------------------------ the icons

def test_an_effect_that_is_installed_and_in_the_chain_shows_both_icons(ed):
    w, _files = ed
    panel = w.catalog_panel
    assert keys(panel, "Hall") == ["pedal", "chain"]  # before, the chain badge replaced the pedal one
    assert keys(panel, "Comp") == ["pedal"]
    assert keys(panel, "12Strings") == [] and keys(panel, "160 Comp") == []


def test_the_icons_differ_in_shape_and_colour(ed):
    w, _files = ed
    w.replace_effect(0, STRINGS)
    badges = {b.key: b for b in card_badges({"installed": True, "in_chain": True, "name": "x"})}
    badges.update({b.key: b for b in card_badges({"installed": False, "in_chain": True, "name": "x"})})
    assert set(badges) == {"pedal", "chain", "warn"}
    assert len({b.icon for b in badges.values()}) == 3 and len({b.token for b in badges.values()}) == 3
    assert badges["warn"].icon == "alert" and badges["warn"].token == "status-warn"


def test_each_icon_has_an_accessible_name_and_a_tooltip(ed):
    w, _files = ed
    panel = w.catalog_panel
    assert ST.ON_PEDAL_NAME == "Instalado en la pedalera" and ST.IN_CHAIN_NAME == "En la cadena del patch"
    assert keys(panel, "Hall") == ["pedal", "chain"]
    spoken = panel.item_of("Hall").data(Qt.ItemDataRole.AccessibleTextRole)
    assert ST.ON_PEDAL_NAME in spoken and ST.IN_CHAIN_NAME in spoken
    assert card_tooltip(panel, "Hall", 0) == ST.ON_PEDAL_NAME
    assert card_tooltip(panel, "Hall", 1) == ST.IN_CHAIN_NAME


# --------------------------------------------------------------- the warning

def test_a_non_installed_effect_in_the_patch_warns_on_its_tile_and_its_card(ed):
    w, _files = ed
    w.replace_effect(0, STRINGS)  # Live is off: allowed, but it warns
    assert effect_ids(w)[0] == STRINGS
    warned = tile(w, 0)
    assert not warned.warn_button.isHidden()
    assert warned.warn_button.toolTip() == ST.NOT_INSTALLED_TIP == "Este efecto no está instalado en la pedalera"
    assert warned.warn_button.accessibleName() == ST.NOT_INSTALLED_TIP
    assert all(t.warn_button.isHidden() for t in w.chain.tiles() if t.slot_index != 0)  # the installed ones do not
    panel = w.catalog_panel
    assert keys(panel, "12Strings") == ["chain", "warn"]
    assert card_tooltip(panel, "12Strings", 1) == ST.NOT_INSTALLED_TIP


def test_no_warnings_and_no_blocks_without_installed_information(qtbot, catalog, tmp_path):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.select_location(1)
    assert w.effect_installed(HALL) is None and w.effect_installed(STRINGS) is None
    w.replace_effect(0, STRINGS)
    assert effect_ids(w)[0] == STRINGS
    assert all(t.warn_button.isHidden() for t in w.chain.tiles())
    assert all("warn" not in keys(w.catalog_panel, n) and "pedal" not in keys(w.catalog_panel, n)
               for n in ("12Strings", "Hall"))
    assert not any("no están en la pedalera" in b for b in w.save_blockers())


def test_a_failed_state_read_leaves_everything_unknown(qtbot, monkeypatch, catalog, tmp_path):
    from zoomstudio.device import PedalClient

    class Unreadable(PedalFiles):
        def install(self, mp) -> None:
            super().install(mp)
            mp.setattr(PedalClient, "read_file", lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))

    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, Unreadable(BEFORE))
    qtbot.wait(300)
    assert w.effect_installed(HALL) is None and w.effect_installed(STRINGS) is None
    w.select_location(2)
    w.replace_effect(0, STRINGS)  # nothing is blocked or flagged on a guess
    assert all(t.warn_button.isHidden() for t in w.chain.tiles()) and w.save_blockers() == []


# ----------------------------------------------------------------- Live blocks

def free_slot(w):
    """Select an empty tile (HB Jazz fills its chain, so Hall goes first) and return its slot index."""
    w.remove_effect(6)
    empty = next(t for t in w.chain.tiles() if t.is_empty)
    w.select_tile(empty.slot_index)
    return empty.slot_index


def go_live(w):
    w.live_check.setChecked(True)
    return free_slot(w)


def pick(w, name):
    panel = w.catalog_panel
    panel.search.setText(name)
    panel.list.setCurrentItem(panel.item_of(name))
    return panel


def test_live_blocks_the_add_button(ed, monkeypatch):
    w, files = ed
    seen = asks(monkeypatch, answer=False)
    go_live(w)
    before, errors = effect_ids(w), []
    w.error_shown.connect(errors.append)
    pick(w, "12Strings").target_button.click()
    assert effect_ids(w) == before
    assert errors and "12Strings" in errors[0] and "no está instalado en la pedalera" in errors[0]
    assert len(seen) == 1 and errors[0] in seen[0][1]  # it offers the install, with the reason
    assert files.files[flst.FLST_NAME] == BEFORE


def test_live_blocks_enter(ed, monkeypatch):
    w, _files = ed
    asks(monkeypatch, answer=False)
    go_live(w)
    before = effect_ids(w)
    panel = pick(w, "12Strings")
    QTest.keyClick(panel.list, Qt.Key.Key_Return)
    assert effect_ids(w) == before


def test_live_blocks_double_click(ed, monkeypatch):
    w, _files = ed
    asks(monkeypatch, answer=False)
    go_live(w)
    before = effect_ids(w)
    panel = pick(w, "12Strings")
    panel.list.itemDoubleClicked.emit(panel.item_of("12Strings"))
    assert effect_ids(w) == before


def test_live_blocks_drag(ed, monkeypatch):
    w, _files = ed
    asks(monkeypatch, answer=False)
    slot = go_live(w)
    before = effect_ids(w)
    drop(tile(w, slot), MIME_EFFECT, STRINGS)
    drop(tile(w, 0), MIME_EFFECT, STRINGS)  # onto an occupied tile too
    assert effect_ids(w) == before


def test_live_still_allows_an_installed_effect(ed, monkeypatch):
    w, _files = ed
    seen = asks(monkeypatch, answer=False)
    slot = go_live(w)
    pick(w, "Comp").target_button.click()
    assert effect_ids(w)[slot] == COMP and not seen


def test_live_off_allows_the_add_and_warns(ed, monkeypatch):
    w, _files = ed
    seen = asks(monkeypatch, answer=False)
    assert not w.live_check.isChecked()
    free_slot(w)
    pick(w, "12Strings").target_button.click()
    assert STRINGS in effect_ids(w) and not seen
    assert any(not t.warn_button.isHidden() for t in w.chain.tiles())


def test_the_block_offers_the_install_and_the_add_goes_through_after_it(ed, qtbot, monkeypatch, tmp_path):
    w, files = ed
    seen = asks(monkeypatch)  # accept the offer, then the install confirmation
    slot = go_live(w)
    pick(w, "12Strings").target_button.click()
    qtbot.waitUntil(lambda: STRINGS in effect_ids(w), timeout=5000)
    assert effect_ids(w)[slot] == STRINGS  # the pending add proceeded
    assert len(seen) == 2 and seen[0][0] == ST.NOT_INSTALLED_TITLE  # the offer, then the install confirmation
    assert files.files["MDL_12ST.ZD2"] and files.files[flst.FLST_NAME] == AFTER
    assert w.effect_installed(STRINGS) is True
    assert tile(w, slot).warn_button.isHidden()


# ----------------------------------------------------------------- quick install

def test_the_target_card_installs_without_leaving_the_editor(ed, qtbot, monkeypatch, tmp_path):
    w, files = ed
    seen = asks(monkeypatch)
    panel = pick(w, "12Strings")
    install = panel.destination.install_button
    assert install.isVisibleTo(panel.destination) and install.text() == ST.INSTALL_ON_PEDAL == "Instalar en la pedalera"
    assert install.isEnabled()
    install.click()
    qtbot.waitUntil(lambda: w.effect_installed(STRINGS) is True, timeout=5000)
    assert len(seen) == 1 and "copia de seguridad" in seen[0][1] and "FLST_SEQ.ZT2" in seen[0][1]  # the existing dialog
    assert files.files[flst.FLST_NAME] == AFTER and "MDL_12ST.ZD2" in files.files
    assert len(list((tmp_path / "effects").glob("*FLST_SEQ.ZT2"))) == 1  # the backup of the list
    assert not w.effects_toggle.isChecked()  # the effects screen never opened
    assert not install.isVisibleTo(panel.destination)  # it is installed now: nothing to offer
    assert keys(panel, "12Strings") == ["pedal"]


def test_the_context_menu_installs_too(ed, qtbot, monkeypatch):
    w, files = ed
    asks(monkeypatch)
    panel = w.catalog_panel
    panel.search.setText("12Strings")
    menu = panel.list.context_menu_for(panel.item_of("12Strings"))
    action = next(a for a in menu.actions() if a.text() == ST.INSTALL_ON_PEDAL)
    assert action.isEnabled()
    action.trigger()
    qtbot.waitUntil(lambda: w.effect_installed(STRINGS) is True, timeout=5000)
    assert files.files[flst.FLST_NAME] == AFTER
    panel.search.setText("Hall")  # an installed effect has no such action
    assert all(a.text() != ST.INSTALL_ON_PEDAL for a in panel.list.context_menu_for(panel.item_of("Hall")).actions())


def test_the_warning_icon_of_a_tile_installs(ed, qtbot, monkeypatch):
    w, files = ed
    asks(monkeypatch)
    w.replace_effect(0, STRINGS)
    tile(w, 0).warn_button.click()
    qtbot.waitUntil(lambda: w.effect_installed(STRINGS) is True, timeout=5000)
    assert files.files[flst.FLST_NAME] == AFTER
    assert all(t.warn_button.isHidden() for t in w.chain.tiles())


def test_declining_the_confirmation_writes_nothing(ed, qtbot, monkeypatch):
    w, files = ed
    seen = asks(monkeypatch, answer=False)
    pick(w, "12Strings").destination.install_button.click()
    qtbot.wait(200)
    assert len(seen) == 1
    assert files.files[flst.FLST_NAME] == BEFORE and "MDL_12ST.ZD2" not in files.files
    assert w.effect_installed(STRINGS) is False


def test_a_read_only_pedal_still_blocks_the_install(qtbot, monkeypatch, catalog, tmp_path):
    files = PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files, member=0x0C)  # a pedal the app cannot edit
    ready(qtbot, w)
    seen = asks(monkeypatch)
    errors = []
    w.error_shown.connect(errors.append)
    panel = pick(w, "12Strings")
    assert w.effect_installed(STRINGS) is False  # reading is allowed: the warning logic still works
    assert not panel.destination.install_button.isEnabled()
    assert not next(a for a in panel.list.context_menu_for(panel.item_of("12Strings")).actions()
                    if a.text() == ST.INSTALL_ON_PEDAL).isEnabled()
    assert w.quick_install(STRINGS) is False
    qtbot.wait(100)
    assert errors == [w.write_block_reason()] and not seen
    assert files.files[flst.FLST_NAME] == BEFORE


# -------------------------------------------------------------------------- save

def test_save_is_blocked_with_the_reason_until_the_effect_is_installed(ed, qtbot, monkeypatch):
    w, _files = ed
    seen = asks(monkeypatch, answer=False)
    w.replace_effect(0, STRINGS)
    assert w.save_blockers() == ["El patch usa efectos que no están en la pedalera: 12Strings"]
    assert not w.save_button.isEnabled()
    assert "El patch usa efectos que no están en la pedalera: 12Strings" in w.save_button.toolTip()
    w.save_current_patch()  # a shortcut can still ask: it offers the install instead of writing
    assert len(seen) == 1 and "12Strings" in seen[0][1]
    asks(monkeypatch)
    tile(w, 0).warn_button.click()
    qtbot.waitUntil(lambda: w.effect_installed(STRINGS) is True, timeout=5000)
    assert w.save_blockers() == []
    assert w.save_button.isEnabled()


def test_the_blocker_lists_every_missing_effect_once(ed):
    w, _files = ed
    w.replace_effect(0, STRINGS)
    w.replace_effect(3, 0x1800030)  # 160 Comp is not installed either
    w.replace_effect(6, STRINGS)
    assert [b for b in w.save_blockers() if "pedalera" in b] == [
        "El patch usa efectos que no están en la pedalera: 12Strings, 160 Comp"]


def test_an_installed_flag_without_its_file_counts_as_not_installed(qtbot, monkeypatch, catalog, tmp_path):
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE, ON_PEDAL[:-1]))  # no OPTCOMP.ZD2
    ready(qtbot, w)
    assert w.effect_installed(OPTCOMP) is False and w.effect_installed(HALL) is True


def test_bulk_write_paths_refuse_effects_the_pedal_lacks(ed, monkeypatch):
    # verifier V3 B1: only SAVE checked the installed state; write-all-dirty and paste still wrote
    w, _ = ed
    asks(monkeypatch, True)
    w.replace_effect(0, STRINGS)
    assert w.save_blockers()
    queued = []
    monkeypatch.setattr(w, "_queue_write", lambda patches: queued.append(sorted(patches)) or False)
    w.write_all_dirty()
    w.copy_patch(2)
    w.paste_patch(1)
    assert queued == []


def test_a_bank_load_refuses_a_patch_whose_effects_the_pedal_lacks(ed, monkeypatch):
    from zoomstudio.patches import edit
    from zoomstudio.patches.zptc import build_zptc

    w, _ = ed
    asks(monkeypatch, True)
    w.replace_effect(0, STRINGS)
    entry = w.bank_store.add(build_zptc(edit.sent_form(w.current_patch)), 2)
    queued = []
    monkeypatch.setattr(w, "_queue_write", lambda patches: queued.append(sorted(patches)) or False)
    w.load_from_bank(entry.id, 1)
    assert queued == []
