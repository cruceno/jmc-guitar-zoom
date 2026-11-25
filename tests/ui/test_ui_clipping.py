"""Nothing static is cut: every visible label, button, check, field and combo has room for its text.

The audit walks the real window with the real theme at two window sizes and in the states a user meets. Text
inside painted cards (effect and patch names) is elided on purpose and is not a widget, so it is not audited.
"""
import dataclasses

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QCheckBox, QComboBox, QLabel, QLineEdit,
                               QPushButton, QToolButton, QWidget)

from test_ui_effects_manager import AFTER, BEFORE, ON_PEDAL, PedalFiles, connected_window, open_screen
from ui_replies import FIXTURES
from update_support import UPDATE_STATES, update_state
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import strings as S
from zoomstudio.ui.main_window import MainWindow
from zoomstudio.ui.painted import PaintedText

EFFECTS = FIXTURES.parent.parent / "effects" / "fixtures"
SIZES = [(1440, 900), (2000, 1056)]
STATES = ["no-patch", "patch-selected", "effects-manager", "effects-repair", "not-installed", "patch-warnings", "usage-many", "usage-one", "usage-none", "usage-incomplete", "tuner", "offline", "bank", "bank-empty", "bank-drag", *UPDATE_STATES]
SLACK = 2  # px of rounding the metrics may differ from the painted text by


@pytest.fixture
def themed(qapp):
    from zoomstudio.ui.fonts import register_fonts
    from zoomstudio.ui.theme import apply_dark_theme

    register_fonts()
    apply_dark_theme(qapp)
    yield
    qapp.setStyleSheet("")


@pytest.fixture(scope="module")
def catalog():
    """The fixture catalog plus enough copies to make the catalog list longer than any window (the real one has 533)."""
    base = load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))
    first = next(iter(base.values()))
    extra = {0x7000000 + i: dataclasses.replace(first, effect_id=0x7000000 + i, name=f"Eco largo {i:02d}",
                                                filename=f"ECO{i:02d}.ZD2") for i in range(60)}
    return {**base, **extra}


def padding(widget: QWidget) -> int:
    """Horizontal room the widget keeps for itself (frame, padding, icon, indicator, clear button)."""
    if isinstance(widget, QCheckBox):
        return 26  # indicator 18 + spacing 8
    if isinstance(widget, QAbstractButton):
        extra = 0 if widget.icon().isNull() else widget.iconSize().width() + 6
        if isinstance(widget, QToolButton) and widget.menu() is not None:
            extra += 12
        return extra + 16
    if isinstance(widget, QComboBox):
        return 40  # 12 + 12 padding, the arrow and the frame
    if isinstance(widget, QLineEdit):
        return 26 + (24 if widget.isClearButtonEnabled() else 0) + 28 * len(widget.actions())
    if isinstance(widget, QLabel):
        return 46 if widget.objectName() == "connectionPill" else widget.margin() * 2
    return 0


def texts_of(widget: QWidget) -> list[str]:
    if isinstance(widget, PaintedText):  # section titles and the patch number are painted, not labels
        return [widget.text()]
    if isinstance(widget, QLabel):
        if widget.wordWrap() or widget.pixmap() is not None and widget.text() == "":
            return []
        return [widget.text()] if widget.textFormat() != Qt.TextFormat.RichText else []
    if isinstance(widget, QToolButton) and widget.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly:
        return []  # undo and redo carry their name as a tooltip only
    if isinstance(widget, (QPushButton, QToolButton, QCheckBox)):
        return [widget.text().replace("&", "")]
    if isinstance(widget, QLineEdit):
        return [widget.text()] + ([widget.placeholderText()] if not widget.text() else [])
    if isinstance(widget, QComboBox):
        return [widget.currentText()]
    return []


def clipped(root: QWidget) -> list[str]:
    found = []
    for w in root.findChildren(QWidget):
        if not w.isVisibleTo(root) or w.width() <= 0:
            continue
        # a widget that lives inside a scroll area's viewport is judged against the viewport, not the screen
        for text in texts_of(w):
            if not text:
                continue
            need = QFontMetrics(w._font if isinstance(w, PaintedText) else w.font()).horizontalAdvance(text) + padding(w)
            if need > w.width() + SLACK:
                found.append(f"{type(w).__name__}({w.objectName() or '-'}) {text!r}: needs {need}px, has {w.width()}px")
    return found


def no_hscroll(root: QWidget) -> list[str]:
    return [f"{type(w).__name__}({w.objectName() or '-'}) shows a horizontal scrollbar"
            for w in root.findChildren(QAbstractScrollArea)
            if w.isVisibleTo(root) and w.horizontalScrollBar().isVisibleTo(w)]


def settle(qtbot, w: MainWindow, size) -> None:
    w.resize(*size)
    w.show()
    qtbot.waitExposed(w)
    qtbot.wait(50)


def build(qtbot, monkeypatch, catalog, tmp_path, state: str) -> MainWindow:
    if state.startswith("update-"):  # the effect-library update flow (a private library, a fake channel)
        return update_state(qtbot, tmp_path, catalog, state)
    if state == "offline":
        w = MainWindow(catalog)
        qtbot.addWidget(w)
        w.load_offline(FIXTURES / "backup")
        return w
    if state == "effects-repair":  # 12Strings is flagged installed but its file is missing: «Falta el archivo» + Reparar
        w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(AFTER, ON_PEDAL))
        open_screen(qtbot, w)
        w.effects_panel.select_effect("MDL_12ST.ZD2")
        return w
    if state.startswith("usage-"):  # «Usado en»: several patches (the list scrolls), one, none, not confirmed yet
        if state == "usage-many":
            import test_ui_effects_manager as manager

            monkeypatch.setattr(manager, "PATCHES", manager.PATCHES * 3)
        w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE))
        open_screen(qtbot, w)
        w.effects_panel.select_effect({"usage-many": "OPTCOMP.ZD2", "usage-one": "HALL.ZD2"}.get(state, "COMP.ZD2"))
        if state == "usage-incomplete":
            w.reload()
        return w
    if state == "patch-warnings":  # three patches using an effect the pedal lacks: the triangles and «⚠ 3»
        import test_ui_effects_manager as manager
        from test_ui_patch_warnings import show_patch_warnings

        monkeypatch.setattr(manager, "PATCHES", manager.PATCHES * 3)
        w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE))
        show_patch_warnings(qtbot, w)
        return w
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, PedalFiles(BEFORE))
    if state.startswith("bank"):  # the bank screen: with cards (one long name, one unknown origin), empty, mid-drag
        if state != "bank-empty":
            from zoomstudio.patches.zptc import build_zptc, parse_zptc
            for i, origin in enumerate((20, 33, None)):
                patch = parse_zptc((FIXTURES / "53-HB-Jazz.zptc").read_bytes())
                patch.name = ("Bank Lead", "WWWWWWWWWW", "Clean")[i]
                w.bank_store.add(build_zptc(patch), origin=origin, now=f"2026112{i}-101500")
        w.bank_button.click()
        w.bank_panel.select_position(44)
        if state == "bank":
            w.bank_panel.select_entry(next(iter(w.bank_store.list())).id if w.bank_store.list() else None)
        if state == "bank-drag":
            w.bank_panel.positions.show_drop_target(43)
            w.bank_panel.bank_list.show_drop_target(True)
        return w
    if state == "not-installed":  # warning on a tile and a card, Live on, «Instalar en la pedalera» on the target card
        from test_ui_install_indicators import show_not_installed

        show_not_installed(qtbot, w)
    elif state == "patch-selected":
        w.select_location(44)
    elif state == "effects-manager":
        w.select_location(44)
        open_screen(qtbot, w)
        w.effects_panel.installed_list.setCurrentRow(0) if hasattr(w.effects_panel, "installed_list") else None
    elif state == "tuner":
        w.tuner_button.click()
        qtbot.waitUntil(lambda: w.tuner_panel.isVisible() or not w.isVisible(), timeout=3000)
    return w


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("state", STATES)
def test_no_static_text_is_clipped(qtbot, monkeypatch, catalog, tmp_path, themed, state, size):
    w = build(qtbot, monkeypatch, catalog, tmp_path, state)
    settle(qtbot, w, size)
    assert clipped(w) == []


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("state", STATES)
def test_no_list_scrolls_sideways(qtbot, monkeypatch, catalog, tmp_path, themed, state, size):
    w = build(qtbot, monkeypatch, catalog, tmp_path, state)
    settle(qtbot, w, size)
    assert no_hscroll(w) == []


@pytest.mark.parametrize("size", [(1280, 760), *SIZES], ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_empty_patch_title_is_shown_in_full(qtbot, monkeypatch, catalog, tmp_path, themed, size):
    w = build(qtbot, monkeypatch, catalog, tmp_path, "no-patch")
    settle(qtbot, w, size)
    need = QFontMetrics(w.name_edit.font()).horizontalAdvance(S.NO_PATCH_SELECTED)
    assert w.name_edit.placeholderText() == S.NO_PATCH_SELECTED
    assert w.name_edit.width() >= need + 12


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_catalog_cards_are_as_wide_as_the_viewport(qtbot, monkeypatch, catalog, tmp_path, themed, size):
    w = build(qtbot, monkeypatch, catalog, tmp_path, "no-patch")
    settle(qtbot, w, size)
    for group in w.catalog_panel.section_groups():  # sections start folded; the width test needs a long list
        if not w.catalog_panel.section_expanded(group):
            w.catalog_panel.toggle_section(group)
    qtbot.wait(50)
    lst = w.catalog_panel.list
    assert lst.verticalScrollBar().isVisibleTo(lst)  # the catalog is long: the scrollbar is what used to steal width
    assert not lst.horizontalScrollBar().isVisibleTo(lst)
    viewport = lst.viewport().width()
    assert lst.visualItemRect(lst.item(0)).width() == viewport
    assert lst.sizeHintForColumn(0) <= viewport


@pytest.mark.parametrize("name", ["", "Bank Lead", "WWWWWWWWWW"])
def test_the_bank_rename_dialog_is_not_clipped(qtbot, themed, name):
    from zoomstudio.ui.bank_screen import RenameDialog

    dialog = RenameDialog(None, name)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert clipped(dialog) == [] and no_hscroll(dialog) == []
