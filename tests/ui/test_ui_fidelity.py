"""Corrections measured against the approved prototype (fidelity batch F01-F20), through the public widgets."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ui_replies import FIXTURES
from zoomstudio.effects.i18n import effect_description
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import strings, tokens
from zoomstudio.ui.glass import BackdropRoot
from zoomstudio.ui.main_window import MainWindow
from zoomstudio.ui.tuner import TunerPanel


@pytest.fixture
def themed(qapp):
    """The real theme: the style sheet is what overrides fonts, so font checks need it."""
    from zoomstudio.ui.fonts import register_fonts
    from zoomstudio.ui.theme import apply_dark_theme

    register_fonts()
    apply_dark_theme(qapp)
    yield
    qapp.setStyleSheet("")


@pytest.fixture
def window(qtbot, themed):
    w = MainWindow(load_catalog(("pedal", FIXTURES / "catalog")))
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.resize(1440, 900)
    w.show()
    return w


def lit_rows(image, predicate):
    """Pixel rows of ``image`` that hold at least one pixel for which ``predicate(QColor)`` is true."""
    return [y for y in range(image.height())
            if any(predicate(image.pixelColor(x, y)) for x in range(0, image.width(), 2))]


# ------------------------------------------------------------------ F01 tuner

def test_tuner_note_is_painted_at_its_real_size_not_the_style_sheet_size(qtbot):
    root = BackdropRoot()
    qtbot.addWidget(root)
    panel = TunerPanel(root)
    panel.resize(900, 700)
    panel.show()
    panel.show_reading("E", -1)
    assert panel._note.paint_font().pixelSize() == 180
    assert panel._pill_text.paint_font().pixelSize() == 18 and panel._offset.paint_font().pixelSize() == 28
    image = panel._note.grab().toImage()
    amber = tokens.color("tuner-near")
    rows = lit_rows(image, lambda c: abs(c.red() - amber.red()) < 40 and abs(c.green() - amber.green()) < 40
                    and abs(c.blue() - amber.blue()) < 40)
    assert len(rows) > 100  # a 180 px «E» is well over 100 px tall; the style sheet font-size made it ~14


def test_tuner_has_title_scale_labels_and_an_exit_button(qtbot):
    root = BackdropRoot()
    qtbot.addWidget(root)
    panel = TunerPanel(root)
    assert panel.title.text() == strings.TUNER_TITLE.upper()
    assert panel.exit_button.text() == strings.TUNER_EXIT and panel.exit_button.key == strings.TUNER_KEY
    with qtbot.waitSignal(panel.exit_requested):
        panel.exit_button.click()


def test_top_button_changes_its_text_while_the_tuner_is_on(window):
    assert window.tuner_button.text() == strings.TUNER
    window._apply_tuner_state(True)
    assert window.tuner_button.text() == strings.TUNER_EXIT
    window.tuner_panel.exit_requested.emit()
    assert not window.tuner_button.isChecked()
    window._apply_tuner_state(False)
    assert window.tuner_button.text() == strings.TUNER


# --------------------------------------------------------------- F02 patch header

def test_patch_header_is_a_number_and_an_editable_name_in_exo_2_40(window):
    window.select_location(44)
    assert window.patch_number.text() == "53" and window.name_edit.text() == window.current_patch.name
    assert window.patch_number.paint_font().pixelSize() == 40
    assert window.name_edit.fontInfo().pixelSize() == 40 and "Exo 2" in window.name_edit.fontInfo().family()
    assert not hasattr(window, "patch_title")  # no «53 HB Jazz (volumen 100)» label any more
    from PySide6.QtWidgets import QLabel

    assert not any("(volumen" in label.text() for label in window.editor_row.findChildren(QLabel))


def test_header_without_a_patch_says_so_in_the_name_placeholder(window):
    window.select_location(1)
    window.patch_list.setCurrentRow(-1)
    window._rebuild_patch_list()
    assert window.name_edit.placeholderText() == strings.NO_PATCH_SELECTED and window.patch_number.text() == ""


# ------------------------------------------------------------------ F03 meters

def test_meters_show_only_the_fill_and_their_value_is_a_label(window):
    for bar in (window.dsp_bar, window.memory_bar, window.task_bar):
        assert not bar.isTextVisible()
    window.select_location(44)
    assert window.dsp_value.text() == strings.dsp_value(window.dsp_percent())
    assert window.memory_value.text() == strings.NOT_AVAILABLE  # no pedal: n/d


def test_dsp_over_the_limit_marks_bar_and_value_red_through_the_over_property(window):
    window.select_location(44)
    assert not window.dsp_bar.property("over")
    window._set_dsp(103.0)
    assert window.dsp_bar.property("over") and window.dsp_value.property("over")
    assert window.dsp_alert.isVisible() and window.dsp_alert.toolTip() == strings.DSP_OVER_LIMIT
    assert window.dsp_bar.styleSheet() == ""  # no inline colour: the QSS rule on the property does it
    window._set_dsp(40.0)
    assert not window.dsp_bar.property("over") and not window.dsp_alert.isVisible()


# ------------------------------------------------------------- F04 / F05 layout

def test_columns_are_248_centre_and_368_wide(window):
    sizes = window.splitter.sizes()
    assert sizes[0] == 248 and sizes[2] == 368 and sizes[1] > 700


def test_centre_is_three_glass_panels_header_chain_and_parameters(window):
    from zoomstudio.ui.glass import GlassPanel

    panels = [w for w in window.centre.children() if isinstance(w, GlassPanel)]
    assert len(panels) == 3
    window.select_location(44)
    from zoomstudio.ui.painted import SectionLabel

    assert strings.CHAIN_TITLE.upper() in [w.text() for w in window.centre.findChildren(SectionLabel)]
    assert window.chain_caption.text() == strings.chain_caption(5, 7)


# ------------------------------------------------------------------ F06 detail card

def test_detail_card_has_a_parameter_column_and_an_effect_column(window):
    window.select_location(44)
    window.select_tile(1)
    p = window.params
    assert p.param_name.text() == p.rows()[0].name and p.help.text()
    assert p.param_facts.text() == strings.param_facts(p.rows()[0].spin.value(), p.rows()[0].maximum, p.rows()[0].default)
    info = window.catalog[window.current_patch.effects[1].effect_id]
    assert p.effect_name.text() == info.name and p.description.text() == effect_description(info)
    assert strings.percent(info.dsp_load_percent) in p.effect_facts.text()
    assert p.chip.text() == strings.group_label(info.group) and p.slot_caption.text() == "Slots 2–3"


def test_a_450_character_description_wraps_and_fits_without_scrolling_at_1440_x_900(window, monkeypatch):
    sentence = "Modelo de un amplificador de combo limpio con graves cálidos, agudos brillantes y trémolo propio. "
    monkeypatch.setattr("zoomstudio.ui.widgets.effect_description", lambda info: (sentence * 5)[:450])
    window.select_location(44)
    window.select_tile(1)
    window.select_tile(0)
    window.select_tile(1)
    scroll = window.params.description_scroll
    assert len(window.params.description.text()) == 450
    assert scroll.verticalScrollBar().maximum() == 0  # all of it is visible: nothing is clipped
    card = window.params.card
    assert card.rect().contains(scroll.mapTo(card, scroll.rect().bottomLeft()))  # and inside the card


def test_empty_slot_explains_how_to_fill_it(window):
    window.select_location(44)
    window.remove_effect(0)
    empty = next(t for t in window.chain_tiles() if t.is_empty)
    window.select_tile(empty.slot_index)
    assert window.params.empty_title.text() == strings.empty_slot_title(empty.slot_index + 1)
    assert not window.params.card.isVisible() and window.params.empty_text.isVisible()


# -------------------------------------------------------- F07 / F08 / F13 catalog

def test_catalog_destination_names_the_slots_and_what_gets_replaced(window):
    window.select_location(44)
    window.select_tile(1)  # FD DLXR, two slots
    dest = window.catalog_panel.destination
    assert dest.text == strings.catalog_destination(1, False, True, "FD DLXR") and "slots 2–3" in dest.text
    assert [t for t in dest.strip if t[2]] == [(window.chain_tiles()[1].group, 2, True)]
    assert len(dest.strip) == len(window.chain_tiles())


def test_catalog_detail_shows_dsp_after_the_replacement(window):
    window.select_location(44)
    window.select_tile(1)
    panel = window.catalog_panel
    panel.search.setText("Comp")
    panel.list.setCurrentRow(panel.visible_names().index("Comp"))
    comp = next(i for i in window.catalog.values() if i.name == "Comp")
    old = window.catalog[window.current_patch.effects[1].effect_id]
    after = window.dsp_percent() - old.dsp_load_percent + comp.dsp_load_percent
    assert panel.after_value.text() == strings.dsp_value(after)
    assert panel.preview.size().width() == 52 and panel.detail_name.text() == "Comp"
    assert panel.list.isVisible() and panel.list.height() > 100  # the preview no longer covers the list


def test_catalog_with_no_match_says_so_and_offers_to_clear_the_search(window):
    panel = window.catalog_panel
    panel.search.setText("zzzq")
    assert panel.visible_names() == [] and panel.none_box.isVisible() and not panel.list.isVisible()
    assert panel.none_label.text() == strings.no_effect_matches("zzzq", "", False)
    panel.clear_button.click()
    assert panel.search.text() == "" and panel.list.isVisible() and not panel.none_box.isVisible()
    assert panel.count_label.text() == strings.visible_count(len(panel.visible_names()))


# ------------------------------------------------------------- F10 / F12 / F16

def test_connection_pill_has_a_dot_kind_per_state(window):
    assert window.connection_label.kind == "info"  # the fixture loaded a folder
    window._set_connection(strings.connected("A1 FOUR"), True)
    assert window.connection_label.kind == "ok"
    window._set_connection(strings.NOT_CONNECTED, False)
    assert window.connection_label.kind == "none"


def test_unsaved_changes_marker_is_a_dot_label_shown_only_when_dirty(window):
    window.select_location(44)
    assert not window.dirty_label.isVisible()
    window.set_param(1, 3, 12)
    assert window.dirty_label.isVisible() and window.dirty_label.text() == strings.UNSAVED_CHANGES


def test_status_bar_lives_in_a_glass_panel_and_marks_errors(window):
    from zoomstudio.ui.glass import GlassPanel

    bar = window.statusBar()
    assert isinstance(bar.parentWidget(), GlassPanel)
    window.statusBar().showMessage("ok")
    assert not bar.property("error")
    window._report_error("falló")
    assert bar.property("error") and "falló" in bar.currentMessage()
    window.statusBar().showMessage("otra")
    assert not bar.property("error")


# ------------------------------------------------------------------ F09 live switch

def test_live_is_a_switch_that_says_si_or_no(window):
    from zoomstudio.ui.painted import LiveSwitch

    assert isinstance(window.live_check, LiveSwitch) and window.live_check.isCheckable()
    assert window.live_check.state_text() == strings.SWITCH_OFF and not window.live_check.isEnabled()
    window.live_check.setEnabled(True)
    window.live_check.click()
    assert window.live_check.isChecked() and window.live_check.state_text() == strings.SWITCH_ON
    assert window.live_check.accessibleName()


# --------------------------------------------------------------- F11 patch list

def test_patch_list_header_counts_patches_in_use(window):
    in_use = sum(1 for p in window._patches.values() if any(not e.is_placeholder for e in p.effects))
    assert window.patches_caption.text() == strings.patches_caption(in_use, 10, 59)


def test_a_patch_without_effects_is_painted_without_a_fill(window):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem

    from zoomstudio.ui.cards import ROLE_STRIP, PatchCardDelegate

    item = window.patch_list.item(0)
    index = window.patch_list.indexFromItem(item)
    option = QStyleOptionViewItem()
    option.rect.setSize(QSize(248, 56))

    def middle_alpha() -> int:
        image = QImage(248, 56, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        PatchCardDelegate().paint(p, option, index)
        p.end()
        return image.pixelColor(124, 28).alpha()

    item.setData(ROLE_STRIP, [("DYNAMICS", 1, True)])
    filled = middle_alpha()
    item.setData(ROLE_STRIP, [(None, 1, False)] * 5)  # a patch whose slots are all empty
    assert middle_alpha() < filled and middle_alpha() < 30  # only the dashed border is drawn


# ------------------------------------------------------------------ F14 / F15 pedals

def test_pedal_that_does_not_run_on_the_a1_says_so_in_place_of_its_group(window):
    window.select_location(44)
    window.allowed_ids = {i for i in window.catalog if i != window.current_patch.effects[0].effect_id}
    window._show_patch(44)
    tile = window.chain_tiles()[0]
    assert tile.problem and tile.body.legend_text() == strings.TILE_PROBLEM
    assert window.chain_tiles()[1].body.legend_text() == ""


def test_empty_pedals_say_what_they_are_for(window):
    window.select_location(44)
    for tile in [t for t in window.chain_tiles() if not t.is_empty and not t.is_wide][:2]:
        window.remove_effect(tile.slot_index)
    empty = next(t for t in window.chain_tiles() if t.is_empty)
    window.select_tile(empty.slot_index)
    assert empty.body.legend_text() == strings.PEDAL_EMPTY_TARGET
    other = next(t for t in window.chain_tiles() if t.is_empty and t is not empty)
    assert other.body.legend_text() == strings.PEDAL_EMPTY_ADD


# ------------------------------------------------------------------ F17 menus

def test_menus_are_glass_with_the_first_item_focused_and_the_history_note(window):
    from zoomstudio.ui.glass import GlassMenu

    menu = window.edit_button.menu()
    assert isinstance(menu, GlassMenu) and isinstance(window.library_button.menu(), GlassMenu)
    note = [a for a in menu.actions() if a.text() == strings.EDIT_MENU_NOTE]
    assert note and not note[0].isEnabled()
    window.select_location(44)
    window.set_param(1, 3, 12)  # something to undo: the first enabled item is Deshacer
    menu.popup(window.edit_button.mapToGlobal(window.edit_button.rect().bottomLeft()))
    assert menu.activeAction() is window.undo_action
    assert not menu.grab().toImage().isNull()
    menu.hide()


def test_write_everything_action_counts_the_edited_patches(window):
    assert window.write_dirty_action.text() == strings.WRITE_DIRTY
    window.select_location(44)
    window.set_param(1, 3, 12)
    assert window.write_dirty_action.text() == strings.write_dirty(1) and "(1)" in window.write_dirty_action.text()


# ------------------------------------------------------------------ F18 dialogs

def test_confirm_dialog_dims_the_window_while_open_and_puts_the_destructive_choice_first(window, qtbot):
    from zoomstudio.ui.dialogs import ConfirmDialog, Scrim

    d = ConfirmDialog(window, "t", "x", strings.DISCARD_ACCEPT, danger=True)
    qtbot.addWidget(d)
    d.show()
    scrim = window.findChild(Scrim)
    assert scrim is not None and scrim.isVisible() and scrim.size() == window.size()
    assert d.cancel_button.isDefault() and d.title_icon.isVisible()
    assert d.accept_button.geometry().left() < d.cancel_button.geometry().left()
    assert not d.grab().toImage().isNull()
    d.close()
    assert window.findChild(Scrim) is None or not window.findChild(Scrim).isVisible()


# ------------------------------------------------------------------ F19 backdrop

def test_backdrop_lights_are_placed_like_the_prototype():
    from PySide6.QtCore import QSize
    from zoomstudio.ui.glass import render_backdrop

    image = render_backdrop(QSize(1440, 900))
    # sampled from the prototype's state-01 gutter, where the backdrop shows untouched: (x, y, rgb)
    for x, y, rgb in [(2, 200, (20, 15, 13)), (2, 450, (12, 10, 11)), (720, 893, (13, 18, 21)),
                      (1430, 60, (17, 20, 29)), (1430, 450, (9, 9, 11)), (200, 3, (22, 17, 14))]:
        c = image.pixelColor(x, y)
        assert max(abs(c.red() - rgb[0]), abs(c.green() - rgb[1]), abs(c.blue() - rgb[2])) <= 4, (x, y)
