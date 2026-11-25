"""The effects screen's pedal filter and the editor's quick install against effects the pedal's list does not name.

The pedal's FLST_SEQ.ZT2 only has records for the effects it knows, and the installer only flips existing flags:
an effect that Guitar Lab lists for the A1 FOUR but that the pedal's list lacks can never be installed from here.
"""
import dataclasses

import pytest
from PySide6.QtCore import Qt

from test_ui_effects_manager import (A1, AFTER, G5N, BEFORE, MDL_12ST, PedalFiles, connected_window, entry_item, names,
                                     open_screen, pedal_registry, pedal_screen)
from test_ui_install_indicators import REAL_READ
from ui_replies import FIXTURES
from zoomstudio.effects import flst
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import strings as ST
from zoomstudio.ui.effects_manager import ROLE_BADGE, ROLE_MODELS
from zoomstudio.ui.main_window import MainWindow

VARIANT = 0x9A09030  # «Hall» again: another model's file and id under the same display name (real: Air / AIR88)
UNLISTED = 0x1800099  # an A1 FOUR effect of Guitar Lab's list that this pedal's FLST_SEQ.ZT2 has no record of
EFFECTS = FIXTURES.parent.parent / "effects" / "fixtures"


@pytest.fixture(scope="module")
def catalog():
    base = load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))
    unlisted = dataclasses.replace(base[MDL_12ST], effect_id=UNLISTED, filename="ZZNEW_100.zd2", name="ZzNew")
    variant = dataclasses.replace(base[0x9000030], effect_id=VARIANT, filename="HALL88_100.zd2")  # name stays «Hall»
    return {**base, UNLISTED: unlisted, VARIANT: variant}


@pytest.fixture(autouse=True)
def reads_the_effect_list(monkeypatch):
    monkeypatch.setattr(MainWindow, "_load_installed_state", REAL_READ)


def registry():
    from zoomstudio.effects.models import PedalModel

    models = pedal_registry(extra_a1=(UNLISTED,))
    models[G5N] = PedalModel(G5N, "G5n", frozenset(models[G5N].effect_ids | {VARIANT}))  # the variant is a G5n file
    return models


def screen(qtbot, monkeypatch, catalog, tmp_path):
    return pedal_screen(qtbot, monkeypatch, catalog, tmp_path, registry=registry())


def test_the_connected_pedal_filter_hides_what_its_list_cannot_install(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = screen(qtbot, monkeypatch, catalog, tmp_path)
    assert panel.pedal_combo.currentData() == A1
    assert names(panel, "available") == ["MDL_12ST.ZD2"]  # HALL88: a G5n file; ZZNEW: the pedal's list has no record; 160 Comp: a G5n effect
    assert names(panel, "installed").count("HALL.ZD2") == 1  # an installed effect never shows twice
    assert panel.available_count.text() == ST.effects_count(1, 1)  # the count is what is shown, not the hidden ones


def test_all_pedals_still_shows_it_with_a_clearer_badge_and_reason(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = screen(qtbot, monkeypatch, catalog, tmp_path)
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData("all"))
    assert "ZZNEW.ZD2" in names(panel, "available")
    assert panel.available_count.text() == ST.effects_count(4, 4)
    item = entry_item(panel, "available", "ZZNEW.ZD2")
    assert item.data(ROLE_BADGE) == ST.EFFECTS_LIST_BADGE and ST.EFFECTS_LIST_BADGE != ST.not_compatible_with("A1 FOUR")
    assert ST.EFFECTS_NOT_IN_LIST_TIP == (
        "La pedalera conectada no incluye este efecto en su lista interna; la app no puede instalarlo")
    assert item.toolTip() == f"{ST.EFFECTS_NOT_IN_LIST_TIP}\nZZNEW.ZD2"  # the reason, then the pedal file name
    assert ST.EFFECTS_NOT_IN_LIST_TIP in item.data(Qt.ItemDataRole.AccessibleTextRole)
    # a model the effect is not for keeps «No compatible con …»
    assert ST.not_compatible_with("A1 FOUR") in entry_item(panel, "available", "160_COMP.ZD2").toolTip()
    panel.select_effect("ZZNEW.ZD2")
    assert panel.reason_label.text() == ST.EFFECTS_NOT_IN_PEDAL_LIST == "No figura en la lista de efectos de esta pedalera"
    assert not panel.install_button.isEnabled()


def test_the_editor_does_not_offer_the_install_of_an_effect_the_pedal_cannot_take(qtbot, monkeypatch, catalog, tmp_path):
    files = PedalFiles(AFTER)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files)
    qtbot.waitUntil(lambda: w.effect_installed(0x9000030) is not None, timeout=5000)
    assert w.effect_installed(UNLISTED) is False
    panel = w.catalog_panel
    panel.search.setText("ZzNew")
    panel.list.setCurrentItem(panel.item_of("ZzNew"))
    button = panel.destination.install_button
    assert button.isVisibleTo(panel.destination) and not button.isEnabled()
    assert button.text() == ST.CANNOT_INSTALL_HERE and button.toolTip() == ST.EFFECTS_NOT_IN_PEDAL_LIST
    action = next(a for a in panel.list.context_menu_for(panel.item_of("ZzNew")).actions()
                  if a.text() in (ST.INSTALL_ON_PEDAL, ST.CANNOT_INSTALL_HERE))
    assert not action.isEnabled()
    errors = []
    w.error_shown.connect(errors.append)
    assert w.quick_install(UNLISTED) is False
    assert errors and flst.FLST_NAME in files.files and files.files[flst.FLST_NAME] == AFTER
    assert "ZZNEW.ZD2" not in files.files
    panel.search.setText("12Strings")  # one the pedal's list names is still offered
    panel.list.setCurrentItem(panel.item_of("12Strings"))
    assert button.isEnabled() and button.text() == ST.INSTALL_ON_PEDAL


def test_same_name_variants_are_told_apart_under_all_pedals(qtbot, monkeypatch, catalog, tmp_path):
    _w, panel, _files = screen(qtbot, monkeypatch, catalog, tmp_path)
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData("all"))
    variant = entry_item(panel, "available", "HALL88.ZD2")
    assert variant.data(ROLE_MODELS) == "Para G5n" == ST.effects_for_models(["G5n"])
    assert ST.not_compatible_with("A1 FOUR") in variant.toolTip()  # the model badge stays on model entries only
    assert "HALL88.ZD2" in variant.toolTip()
    assert ST.effects_other_version_installed("Hall", "HALL.ZD2") in variant.toolTip()
    assert ST.effects_other_version_installed("Hall", "HALL.ZD2") == "Otra versión de Hall instalada (HALL.ZD2)"
    assert entry_item(panel, "available", "ZZNEW.ZD2").data(ROLE_MODELS) == "Para A1 FOUR"
    assert entry_item(panel, "available", "ZZNEW.ZD2").data(ROLE_BADGE) == ST.EFFECTS_LIST_BADGE  # not «No compatible»
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData(A1))
    assert "HALL88.ZD2" not in names(panel, "available")  # and the connected pedal's view has no subtitles
