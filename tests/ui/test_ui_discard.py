"""«Descartar cambios»: revert a patch to its last saved version as one undoable step."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton

from test_ui_editor import (B1, BACKUP, COMP, HB_BYTES, catalog, connected, ids, wire,  # noqa: F401 (catalog: fixture)
                            queue_save)
from test_ui_clipping import themed  # noqa: F401 (fixture)
from ui_replies import FIXTURES
from jmc_guitar_zoom.device import sysex
from jmc_guitar_zoom.patches import edit
from jmc_guitar_zoom.patches.zptc import build_zptc, parse_zptc
from jmc_guitar_zoom.ui import strings as ST
from jmc_guitar_zoom.ui.dialogs import ConfirmDialog
from jmc_guitar_zoom.ui.main_window import DISCARD_SHORTCUT, MainWindow, live_restore_messages


@pytest.fixture
def window(qtbot, catalog, tmp_path):
    w = MainWindow(catalog, backup_dir=tmp_path / "autosave", bank_dir=tmp_path / "bank")
    qtbot.addWidget(w)
    w.load_offline(BACKUP)
    w.select_location(44)
    return w


def edit_everything(w):
    """A rename, a volume change, a parameter and a power switch: four different kinds of edit."""
    w.rename_patch("Changed")
    w.set_patch_volume(33)
    w.set_param(1, 1, 60)
    w.set_effect_enabled(0, False)


def test_reverting_restores_name_volume_chain_and_parameters_and_clears_dirty(window):
    saved = window.current_patch
    edit_everything(window)
    window.replace_effect(6, COMP)
    assert window.is_dirty(44) and window.discard_button.isEnabled()
    assert window.discard_changes() is True
    assert window.current_patch == saved
    assert not window.is_dirty(44) and not window.discard_button.isEnabled()
    assert window.name_edit.text() == saved.name and window.volume_spin.value() == saved.volume
    assert [t.effect_name for t in window.chain_tiles() if not t.is_empty][-1] == "Hall"
    assert not window.save_button.isEnabled()


def test_undo_after_a_revert_brings_the_edits_back(window):
    saved = window.current_patch
    edit_everything(window)
    edited = window.current_patch
    window.discard_changes()
    assert window.undo_group.undoText() == ST.DISCARD_ACCEPT  # one undo step named «Descartar cambios»
    window.undo()
    assert window.current_patch == edited and window.is_dirty(44)
    window.redo()
    assert window.current_patch == saved and not window.is_dirty(44)


def test_the_button_is_disabled_on_a_clean_patch(window):
    assert not window.discard_button.isEnabled() and not window.discard_action.isEnabled()
    assert window.discard_changes() is False
    window.rename_patch("x")
    assert window.discard_button.isEnabled() and window.discard_action.isEnabled()


def test_a_declined_confirmation_changes_nothing(window, monkeypatch):
    edit_everything(window)
    edited = window.current_patch
    asked = []
    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(lambda parent, title, text, *a, **k: asked.append((title, text)) or False))
    assert window.discard_changes() is False
    assert window.current_patch == edited and window.is_dirty(44)
    assert len(asked) == 1 and "Changed" in asked[0][0] and "Deshacer" in asked[0][1]


def test_the_edit_menu_and_the_shortcut_are_there(window):
    action = next(a for a in window.edit_button.menu().actions() if a.text() == ST.DISCARD_ACCEPT)
    assert action is window.discard_action and action.shortcut().toString() == DISCARD_SHORTCUT == "Ctrl+R"
    window.rename_patch("x")
    action.trigger()
    assert not window.is_dirty(44)


def test_the_patch_list_menu_reverts_any_dirty_patch_not_only_the_selected_one(window):
    window.rename_patch("Other")  # location 44 is dirty
    window.select_location(1)  # ... and no longer the selected one
    assert window.is_dirty(44) and window.current_location == 1
    menu = window.patch_menu(44)
    revert = next(a for a in menu.actions() if a.text() == ST.DISCARD_ACCEPT)
    revert.trigger()
    assert not window.is_dirty(44) and window.current_location == 1
    assert window._patches[44].name != "Other"
    assert all(a.text() != ST.DISCARD_ACCEPT for a in window.patch_menu(44).actions())  # clean: not offered
    assert all(a.text() != ST.DISCARD_ACCEPT for a in window.patch_menu(1).actions())


def test_both_header_buttons_are_icon_only_with_names_and_tooltips(window):
    window.rename_patch("x")
    for button, name in ((window.save_button, ST.SAVE_TO_PEDAL), (window.discard_button, ST.DISCARD_CHANGES_TIP)):
        assert isinstance(button, QAbstractButton) and button.text() == "" and not button.icon().isNull()
        assert name in button.accessibleName() and name in button.toolTip()
        assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert DISCARD_SHORTCUT in window.discard_button.toolTip()
    assert window.save_button.accessibleName().endswith("posición 53)")  # the display number of location 44


def test_live_off_sends_nothing_and_live_on_sends_the_baseline_values(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    saved = w.current_patch
    w.set_param(1, 1, 60)
    w.rename_patch("Edited")
    w.set_patch_volume(20)
    before = len(t.sent)
    assert w.discard_changes() is True
    qtbot.wait(150)
    assert len(t.sent) == before  # Live is off: nothing goes to the pedal
    w.set_param(1, 1, 60)
    w.rename_patch("Edited")
    w.set_patch_volume(20)
    w.live_check.setChecked(True)
    qtbot.waitUntil(lambda: t.sent[-1].__class__.__name__ == "ProgramChange", timeout=3000)
    mark = len(t.sent)
    assert w.discard_changes() is True
    m = 0x6E
    last = sysex.set_patch_volume(saved.volume, m)  # the restore ends with the volume
    qtbot.waitUntil(lambda: last in [m_.data for m_ in t.sent[mark:] if hasattr(m_, "data")], timeout=3000)
    sent = [m_.data for m_ in t.sent[mark:] if hasattr(m_, "data")]
    assert sysex.set_param(1, 3, saved.effects[1].params[1], m) in sent  # the parameter edited live goes back
    assert sysex.set_patch_volume(saved.volume, m) in sent
    assert sysex.set_patch_name_char(0, saved.name.ljust(10)[0], m) in sent
    assert all(not d.startswith(sysex.header(m) + b"\x45") for d in sent)  # never a write to pedal memory
    w.close()


def test_after_a_save_the_new_baseline_is_the_saved_version(qtbot, catalog, tmp_path):
    w, t = connected(qtbot, catalog, tmp_path)
    w.set_param(1, 1, 60)
    w.rename_patch("Saved")
    expected = build_zptc(edit.sent_form(w.current_patch))
    readback = build_zptc(edit.with_fillers(parse_zptc(expected), catalog))
    queue_save(t, previous=HB_BYTES, readback=readback)
    with qtbot.waitSignal(w.save_finished, timeout=5000):
        w.save_button.click()
    assert not w.is_dirty(44) and not w.discard_button.isEnabled()
    saved = w.current_patch
    w.rename_patch("After")  # names hold 10 characters
    assert w.discard_changes() is True
    assert w.current_patch == saved and w.current_patch.name == "Saved" and not w.is_dirty(44)
    w.close()


def _luminance(c) -> float:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def _contrast(a, b) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("which", ["save_button", "discard_button"])
def test_the_icon_has_at_least_3_to_1_contrast_in_both_states(window, themed, which):
    button = getattr(window, which)
    window.show()
    results = {}
    for state in ("disabled", "enabled"):
        if state == "enabled":
            window.rename_patch("x")
            button.setEnabled(True)  # the save button also needs a connection; the look is what is measured
        else:
            button.setEnabled(False)
        image = button.grab().toImage()
        h, w = image.height(), image.width()
        # the icon sits in the middle; the background is read where nothing is painted (inside the round edge)
        background = image.pixelColor(w // 2, 8 if h > 20 else 1)
        centre = [image.pixelColor(x, y) for x in range(w // 2 - 11, w // 2 + 11) for y in range(h // 2 - 11, h // 2 + 11)]
        icon = max(centre, key=lambda c: _contrast(c, background))
        results[state] = _contrast(icon, background)
    assert results["enabled"] >= 3 and results["disabled"] >= 3, results
    assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
