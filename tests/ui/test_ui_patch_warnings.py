"""The amber warning on patches that use effects the pedal lacks: patch list, header count, bank, «Usado en».

Same setup as the S6 tests: the window with an in-memory pedal file system behind a scripted FakeTransport. The
patch list repeats HB Jazz at locations 2, 4 and 6, so several patches can be affected at once.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import test_ui_effects_manager as manager
from test_ui_effects_manager import BEFORE, ON_PEDAL, PedalFiles, connected_window, open_screen
from test_ui_install_indicators import REAL_READ, STRINGS, asks, ready  # noqa: F401 (REAL_READ: the fixture below)
from ui_replies import FIXTURES
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.patches import edit
from zoomstudio.patches.zptc import build_zptc, parse_zptc
from zoomstudio.ui import strings as ST
from zoomstudio.ui.cards import ROLE_MISSING
from zoomstudio.ui.main_window import MainWindow

COMP_160 = 0x1800030
EFFECTS = FIXTURES.parent.parent / "effects" / "fixtures"
TIP_2 = "Usa efectos que no están en la pedalera: 12Strings"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


@pytest.fixture(autouse=True)
def reads_the_effect_list(monkeypatch):
    monkeypatch.setattr(MainWindow, "_load_installed_state", REAL_READ)


@pytest.fixture
def ed(qtbot, monkeypatch, catalog, tmp_path):
    monkeypatch.setattr(manager, "PATCHES", manager.PATCHES * 3)  # six patches: 2, 4 and 6 are HB Jazz
    files = PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files)
    ready(qtbot, w)
    return w, files


def missing(w):
    """Location -> the names the card warns about (only the cards that warn)."""
    found = {}
    for i in range(w.patch_list.count()):
        names = w.patch_list.item(i).data(ROLE_MISSING)
        if names:
            found[i + 1] = list(names)
    return found


def use(w, location, slot, effect):
    w.select_location(location)
    w.replace_effect(slot, effect)


# --------------------------------------------------------------- the patch list

def test_only_the_affected_patch_cards_show_the_triangle_with_the_names(ed):
    w, _files = ed
    assert missing(w) == {}  # every effect of every patch is installed
    use(w, 2, 0, STRINGS)
    use(w, 6, 0, STRINGS)
    use(w, 6, 3, COMP_160)
    assert missing(w) == {2: ["12Strings"], 6: ["12Strings", "160 Comp"]}
    first, second = w.patch_list.item(1), w.patch_list.item(5)
    assert first.toolTip() == TIP_2 == ST.patch_missing_tip(["12Strings"])
    assert TIP_2 in first.data(Qt.ItemDataRole.AccessibleTextRole)
    assert second.toolTip() == "Usa efectos que no están en la pedalera: 12Strings, 160 Comp"
    assert w.patch_list.item(3).toolTip() == "" and not w.patch_list.item(3).data(ROLE_MISSING)


def test_no_triangle_without_installed_information(qtbot, catalog, tmp_path):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    use(w, 1, 0, STRINGS)
    assert missing(w) == {} and w.missing_button.isHidden()


def test_the_triangle_follows_an_install_and_a_chain_edit(ed, qtbot, monkeypatch):
    w, _files = ed
    asks(monkeypatch)
    use(w, 2, 0, STRINGS)
    assert missing(w) == {2: ["12Strings"]}
    w.undo()  # a chain edit: the effect goes back
    assert missing(w) == {}
    w.redo()
    assert missing(w) == {2: ["12Strings"]}
    assert w.quick_install(STRINGS)
    qtbot.waitUntil(lambda: w.effect_installed(STRINGS) is True, timeout=5000)
    assert missing(w) == {} and w.missing_button.isHidden()


def test_a_flagged_effect_without_its_file_counts_as_missing(qtbot, monkeypatch, catalog, tmp_path):
    monkeypatch.setattr(manager, "PATCHES", manager.PATCHES * 3)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE, ON_PEDAL[:-1]))  # no OPTCOMP.ZD2
    ready(qtbot, w)
    assert set(missing(w)) == {1, 2, 3, 4, 5, 6} and all("OptComp" in n for n in missing(w).values())


# ------------------------------------------------------------- the header count

def test_the_header_counts_the_affected_patches_and_cycles_through_them(ed):
    w, _files = ed
    assert w.missing_button.isHidden()
    for location in (2, 4, 6):
        use(w, location, 0, STRINGS)
    w.select_location(1)
    button = w.missing_button
    assert not button.isHidden() and button.text() == "3"
    assert button.toolTip() == "3 patches usan efectos que no están en la pedalera" == ST.patches_missing_tip(3)
    assert button.accessibleName() == button.toolTip()
    seen = []
    for _ in range(4):
        button.click()
        seen.append(w.current_location)
    assert seen == [2, 4, 6, 2]  # next affected patch, then round again
    QTest.keyClick(button, Qt.Key.Key_Return)
    assert w.current_location == 4
    w.select_location(2)
    w.undo()
    assert missing(w).keys() == {4, 6} and button.text() == "2"
    assert ST.patches_missing_tip(1) == "1 patch usa efectos que no están en la pedalera"


# ------------------------------------------------------------------------- bank

def bank_patch(catalog, effect):
    patch = parse_zptc((FIXTURES / "53-HB-Jazz.zptc").read_bytes())
    return build_zptc(edit.replace_effect(patch, 0, effect, catalog) if effect else patch)


def test_bank_cards_warn_for_missing_effects(ed, qtbot, monkeypatch, catalog):
    w, _files = ed
    asks(monkeypatch)
    w.bank_store.add(bank_patch(catalog, None), origin=2, now="20261125-101500")
    w.bank_store.add(bank_patch(catalog, STRINGS), origin=2, now="20261125-101600")
    use(w, 2, 0, STRINGS)
    w.bank_button.click()
    assert w.bank_panel.bank_list.count() == 2
    warned = [w.bank_panel.bank_list.item(i) for i in range(w.bank_panel.bank_list.count())
              if w.bank_panel.bank_list.item(i).data(ROLE_MISSING)]
    assert len(warned) == 1 and list(warned[0].data(ROLE_MISSING)) == ["12Strings"]
    assert warned[0].toolTip() == TIP_2
    position = w.bank_panel.positions  # the pedal's own position cards
    assert [i + 1 for i in range(position.count()) if position.item(i).data(ROLE_MISSING)] == [2]
    assert w.quick_install(STRINGS)
    qtbot.waitUntil(lambda: w.effect_installed(STRINGS) is True, timeout=5000)
    assert not any(w.bank_panel.bank_list.item(i).data(ROLE_MISSING) for i in range(w.bank_panel.bank_list.count()))
    assert not any(position.item(i).data(ROLE_MISSING) for i in range(position.count()))


# ------------------------------------------------------------------ «Usado en»

def test_the_usage_cards_of_the_effects_screen_warn_too(qtbot, monkeypatch, catalog, tmp_path):
    monkeypatch.setattr(manager, "PATCHES", manager.PATCHES * 3)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE, ON_PEDAL[:-1]))  # OptComp: no file
    ready(qtbot, w)
    panel = open_screen(qtbot, w)
    panel.select_effect("OPTCOMP.ZD2")
    qtbot.waitUntil(lambda: panel.usage_list.count() > 0, timeout=3000)
    cards = [panel.usage_list.item(i) for i in range(panel.usage_list.count())]
    assert cards and all(list(c.data(ROLE_MISSING)) == ["OptComp"] for c in cards)
    assert ST.patch_missing_tip(["OptComp"]) in cards[0].toolTip()


def show_patch_warnings(qtbot, w):
    """The state the audits look at: three patches with a missing effect, so the header shows «⚠ 3» and the cards warn."""
    w._request_effects_state()  # the audits' windows read nothing by themselves
    qtbot.waitUntil(lambda: w.effect_installed(0x9000030) is not None, timeout=5000)
    for location in (2, 4, 6):
        use(w, location, 0, STRINGS)
    w.select_location(2)
