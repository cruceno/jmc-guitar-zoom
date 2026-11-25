"""Any pedal model Guitar Lab lists drives the lists and the texts; one the app cannot edit yet is read only."""
import pytest

from test_ui_effects_manager import (AFTER, BEFORE, COMP_160, MDL_12ST, ON_PEDAL, PedalFiles, connected_window, names,
                                     open_screen)
from ui_replies import FIXTURES
from zoomstudio.effects import flst
from zoomstudio.effects import models as pm
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.effects.models import A1_FOUR, PedalModel
from zoomstudio.ui import strings as ST

G1 = 0x6E000C00
from fixture_files import EFFECTS  # noqa: E402


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


@pytest.fixture
def registry(catalog):
    return {A1_FOUR: PedalModel(A1_FOUR, "A1 FOUR", frozenset(catalog)),  # the A1 FOUR runs every effect of the fixtures
            G1: PedalModel(G1, "G1 FOUR", frozenset({COMP_160, 0x1000010}))}


def connect(qtbot, monkeypatch, catalog, tmp_path, registry, member, files=None):
    monkeypatch.setattr(pm, "SUPPORTED_MODELS", {A1_FOUR})
    files = files or PedalFiles(BEFORE)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files, models=registry, member=member)
    return w, files


def test_the_connected_model_drives_the_lists_and_every_text_names_it(qtbot, monkeypatch, catalog, tmp_path, registry):
    w, _files = connect(qtbot, monkeypatch, catalog, tmp_path, registry, 0x0C)
    assert w.connected_model == G1 and w.target_model == G1
    panel = w.catalog_panel
    assert panel.count_label.text() == ST.compatible_count(len(panel.visible_names()), "G1 FOUR")
    assert "G1 FOUR" in panel.count_label.text() and "A1 FOUR" not in panel.count_label.text()
    assert "G1 FOUR" in w.connection_label.text()
    screen = open_screen(qtbot, w)
    assert screen.pedal_combo.itemText(0) == "G1 FOUR (conectada)"
    screen.select_effect("MDL_12ST.ZD2")  # an A1 effect: not for the G1 FOUR
    assert screen.reason_label.text() == ST.effects_not_compatible_reason("G1 FOUR")
    assert "A1 FOUR" not in screen.reason_label.text()


def test_a_known_but_unsupported_pedal_shows_a_calm_banner(qtbot, monkeypatch, catalog, tmp_path, registry):
    w, _files = connect(qtbot, monkeypatch, catalog, tmp_path, registry, 0x0C)
    w.show()
    assert w.pedal_notice.isVisibleTo(w)
    assert w.pedal_notice.text() == ST.pedal_readonly_banner("G1 FOUR")
    assert ST.pedal_readonly_banner("G1 FOUR") == ("G1 FOUR detectada: la edición todavía no está verificada en este modelo; "
                                                   "solo lectura")
    assert not w.pedal_notice.property("blocking")


def test_every_write_path_is_blocked_with_the_reason_and_reading_still_works(qtbot, monkeypatch, catalog, tmp_path, registry):
    w, files = connect(qtbot, monkeypatch, catalog, tmp_path, registry, 0x0C)
    reason = ST.pedal_readonly_reason("G1 FOUR")
    assert not w._can_write and w.write_block_reason() == reason
    assert w.patch_list.count() > 0  # the patches were read
    # save
    w.select_location(2)
    w.rename_patch("Edited")
    assert not w.save_button.isEnabled() and reason in w.save_button.toolTip()
    errors = []
    w.error_shown.connect(errors.append)
    w.save_current_patch()
    assert errors and reason in errors[-1]
    # live
    assert not w.live_check.isEnabled()
    # library writes
    errors.clear()
    w.write_all_dirty()
    assert errors and reason in errors[-1]
    # the bank
    errors.clear()
    w.stash_position(2)
    assert errors and reason in errors[-1]
    # effects: install, remove, repair (the buttons and the slots behind them)
    screen = open_screen(qtbot, w)
    assert names(screen, "installed")  # browsing works
    for file in ("COMP.ZD2", "MDL_12ST.ZD2"):
        screen.select_effect(file)
        assert not screen.install_button.isEnabled() and not screen.remove_button.isEnabled()
        assert screen.reason_label.text() in (reason, ST.effects_not_compatible_reason("G1 FOUR"))
    for call in (lambda: w._on_effect_install("MDL_12ST.ZD2", "x"), lambda: w._on_effect_remove("COMP.ZD2"),
                 lambda: w._on_effect_repair("MDL_12ST.ZD2", "x")):
        errors.clear()
        call()
        assert errors and reason in errors[-1]
    qtbot.wait(200)
    assert files.files[flst.FLST_NAME] == BEFORE and "MDL_12ST.ZD2" not in files.files and "COMP.ZD2" in files.files


def test_an_unknown_model_falls_back_to_the_a1_four_with_a_banner_and_is_read_only(qtbot, monkeypatch, catalog, tmp_path, registry):
    w, _files = connect(qtbot, monkeypatch, catalog, tmp_path, registry, 0x2F)
    w.show()
    assert w.connected_model == 0x6E002F00 and w.target_model == A1_FOUR  # the last target, else the A1 FOUR
    assert w.pedal_notice.isVisibleTo(w) and w.pedal_notice.text() == ST.pedal_unknown_banner(0x6E002F00)
    assert w.pedal_notice.text().startswith("Pedal no reconocido (modelo 0x6E002F00)")
    assert "A1 FOUR" in w.catalog_panel.count_label.text()
    assert not w._can_write and w.write_block_reason() == ST.pedal_unknown_reason()


def test_the_a1_four_is_unchanged_and_writable(qtbot, monkeypatch, catalog, tmp_path, registry):
    w, _files = connect(qtbot, monkeypatch, catalog, tmp_path, registry, 0x11)
    w.show()
    assert w.connected_model == A1_FOUR and w._can_write and w.write_block_reason() is None
    assert not w.pedal_notice.isVisibleTo(w)
    w.select_location(2)
    w.rename_patch("Edited")
    assert w.save_button.isEnabled() and w.live_check.isEnabled()
    screen = open_screen(qtbot, w)
    screen.select_effect("MDL_12ST.ZD2")
    assert screen.install_button.isEnabled()
    assert "A1 FOUR (conectada)" == screen.pedal_combo.itemText(0)


def test_live_sends_nothing_to_a_read_only_pedal_even_with_the_switch_forced_on(qtbot, monkeypatch, catalog, tmp_path, registry):
    """The switch is disabled and a disconnect unchecks it, but the two live send paths must not rely on that."""
    w, _files = connect(qtbot, monkeypatch, catalog, tmp_path, registry, 0x0C)
    assert w.write_block_reason() is not None
    sent = w._worker._transport.sent
    w.select_location(2)
    w.live_check.setChecked(True)  # forced: the UI cannot reach this
    w._live_location = w._location
    qtbot.wait(100)
    start = len(sent)
    w.set_param(0, 0, 1)  # an edit: its live send is gated
    w._live_send(0, 0, 1)
    w.discard_changes()  # the Live branch of the discard restores the pedal's edit buffer: gated too
    qtbot.wait(200)
    assert not any(hasattr(m, "data") and b"\x64\x03" in bytes(m.data)[:6] for m in sent[start:])  # no set_param
