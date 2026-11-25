"""Compact windows: nothing overlaps, squeezes or spills, at the 1280×760 minimum and larger, and scaled.

``test_ui_clipping`` measures text width at one size. This audit looks at geometry: siblings must not
intersect, no widget may be given less than its minimum size (which is how painted parts end up on top of each
other), nothing may show outside the window or under the status bar, and the parts of a parameter card (knob,
value, range, spin) must fit its box.
"""
import os
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import (QAbstractScrollArea, QLabel, QScrollBar, QSizePolicy, QStatusBar, QToolButton,
                               QWidget)

from test_ui_effects_manager import AFTER, BEFORE, PATCHES, PedalFiles
from test_ui_clipping import SLACK, clipped, themed  # noqa: F401 (themed is a fixture)
from ui_replies import FIXTURES, HDR, S, fake_pedal
from zoomstudio.device import sysex
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui.main_window import MainWindow
from zoomstudio.ui.painted import SearchField
from zoomstudio.ui.widgets import ParamRow

EFFECTS = FIXTURES.parent.parent / "effects" / "fixtures"
SIZES = [(1280, 760), (1440, 900), (1600, 1000)]
STATES = ["two-pedals", "no-patch", "gt-geq-7", "effects-manager", "bank", "tuner", "offline"]
SQUEEZE_SLACK = 1


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


def build(qtbot, monkeypatch, catalog, tmp_path, state: str) -> MainWindow:
    if state == "two-pedals":  # the pedal selector of the catalog shows when more than one pedal is supported
        from zoomstudio.effects import models as pedal_models

        registry = pedal_models.load_models(FIXTURES / "AllZDL7_2.lst")
        monkeypatch.setattr(pedal_models, "SUPPORTED_MODELS", {pedal_models.A1_FOUR, 0x6E000000})
        w = MainWindow(catalog, models=registry, bank_dir=tmp_path / "bank")
        qtbot.addWidget(w)
        w.load_offline(FIXTURES / "backup")
        return w
    if state == "offline":
        w = MainWindow(catalog, bank_dir=tmp_path / "bank")
        qtbot.addWidget(w)
        w.load_offline(FIXTURES / "backup")
        return w
    PedalFiles(BEFORE).install(monkeypatch)
    transport = fake_pedal(PATCHES)
    for _ in range(30):
        transport.on(sysex.pc_mode(True, 0x6E), S(HDR + b"\x00\x00"))
        transport.on(sysex.pc_mode(False, 0x6E), S(HDR + b"\x00\x00"))
        transport.on(sysex.pc_mode(True, 0x6E), S(HDR + b"\x00\x00"))
    w = MainWindow(catalog, transport_factory=lambda: transport, backup_dir=tmp_path, bank_dir=tmp_path / "bank")
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    if state == "gt-geq-7":
        w.select_location(2)  # HB Jazz
        tile = next(t for t in w.chain_tiles() if t.effect_name == "Gt GEQ 7")
        w.select_tile(tile.slot_index)
    elif state == "effects-manager":
        w.select_location(2)
        with qtbot.waitSignal(w.effects_panel.state_shown, timeout=5000):
            w.open_effects_screen()
        w.effects_panel.select_effect("HALL.ZD2")
    elif state == "bank":
        w.bank_button.setChecked(True)
    elif state == "tuner":
        w.tuner_button.click()
        qtbot.waitUntil(lambda: w.tuner_panel.isVisible() or not w.isVisible(), timeout=3000)
    return w


def settle(qtbot, w: MainWindow, size) -> None:
    w.resize(*size)
    w.show()
    qtbot.waitExposed(w)
    qtbot.wait(80)


def shown(root: QWidget) -> list[QWidget]:
    return [w for w in root.findChildren(QWidget) if w.isVisibleTo(root) and w.width() > 0 and w.height() > 0]


def in_scroll_viewport(w: QWidget) -> bool:
    """A widget inside a scroll area is clipped by it: it may lie outside the window legitimately."""
    p = w.parentWidget()
    while p is not None:
        if isinstance(p.parentWidget(), QAbstractScrollArea) and p.parentWidget().viewport() is p:
            return True
        p = p.parentWidget()
    return False


def label(w: QWidget) -> str:
    text = w.text() if hasattr(w, "text") and callable(w.text) else ""
    return f"{type(w).__name__}({w.objectName() or '-'}){f' {text!r}' if isinstance(text, str) and text else ''}"


def sibling_overlaps(root: QWidget) -> list[str]:
    found = []
    for parent in [root, *root.findChildren(QWidget)]:
        if not parent.isVisibleTo(root) or parent.layout() is None:
            continue
        kids = [c for c in parent.children() if isinstance(c, QWidget) and c.isVisibleTo(root)
                and c.width() > 0 and c.height() > 0 and not c.isWindow()]
        for i, a in enumerate(kids):
            for b in kids[i + 1:]:
                if "removeButton" in (a.objectName(), b.objectName()):
                    continue  # the close mark of a chain tile sits on top of its body on purpose
                inter = a.geometry().intersected(b.geometry())
                if inter.width() > 1 and inter.height() > 1:
                    found.append(f"{label(a)} overlaps {label(b)} inside {label(parent)} ({inter.width()}x{inter.height()})")
    return found


def squeezed(root: QWidget) -> list[str]:
    """A widget a layout shrank below its own minimum size: its parts are then painted over each other."""
    found = []
    for w in shown(root):
        if isinstance(w, (QScrollBar, QStatusBar)) or w.layout() is None and isinstance(w, QAbstractScrollArea):
            continue
        if isinstance(w, QAbstractScrollArea) or (isinstance(w, QLabel) and w.wordWrap()):
            continue
        if isinstance(w, QToolButton) and w.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly:
            continue  # undo and redo: the text is only their tooltip
        policy = w.sizePolicy()
        need = w.minimumSizeHint()
        if need.width() > w.width() + SQUEEZE_SLACK and policy.horizontalPolicy() != QSizePolicy.Policy.Ignored \
                and w.minimumWidth() == 0:
            found.append(f"{label(w)} is {w.width()}px wide, needs {need.width()}")
        if need.height() > w.height() + SQUEEZE_SLACK and policy.verticalPolicy() != QSizePolicy.Policy.Ignored \
                and w.minimumHeight() == 0:
            found.append(f"{label(w)} is {w.height()}px tall, needs {need.height()}")
    return found


def spilled(root: QWidget) -> list[str]:
    """Visible widgets outside the window, or under the status bar."""
    window = QRect(0, 0, root.width(), root.height())
    status = root.statusBar()
    status_rect = QRect(status.mapTo(root, QPoint(0, 0)), status.size())
    found = []
    for w in shown(root):
        if in_scroll_viewport(w) or w is status or status.isAncestorOf(w):
            continue
        rect = QRect(w.mapTo(root, QPoint(0, 0)), w.size())
        if not window.contains(rect):
            found.append(f"{label(w)} lies outside the window {rect.getRect()}")
        elif rect.intersects(status_rect.adjusted(0, 1, 0, 0)) and not w.isAncestorOf(status):
            found.append(f"{label(w)} lies under the status bar")
    return found


def param_cards(root: QWidget) -> list[str]:
    """The knob, the name, the spin and the range of a parameter card must be inside it and apart."""
    found = []
    for card in root.findChildren(ParamRow):
        if not card.isVisibleTo(root):
            continue
        parts = {"name": card.label, "knob": card.dial, "spin": card.spin, "range": card.range_label}
        inner = card.rect()
        rects = {k: QRect(v.mapTo(card, QPoint(0, 0)), v.size()) for k, v in parts.items()}
        for k, r in rects.items():
            if not inner.contains(r):
                found.append(f"card {card.name!r}: {k} {r.getRect()} leaves the card {inner.getRect()}")
        keys = list(rects)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                inter = rects[a].intersected(rects[b])
                if inter.width() > 1 and inter.height() > 1:
                    found.append(f"card {card.name!r}: {a} overlaps {b}")
        area = card.parentWidget().parentWidget().parentWidget() if card.parentWidget() else None
        view = getattr(area, "viewport", lambda: None)()
        if view is not None and card.pos().y() == 0:  # the first row of cards must be seen, not squeezed away
            seen = view.rect().contains(QRect(card.mapTo(view, QPoint(0, 0)), card.size()))
            if not seen:
                found.append(f"card {card.name!r}: the first row is not fully inside the card area")
        need = card.range_label.fontMetrics().horizontalAdvance(card.range_label.text())
        if not card.range_label.wordWrap() and need > card.range_label.width() + SLACK:
            found.append(f"card {card.name!r}: range text is cut")
    return found


def scroll_content_clipped(root: QWidget) -> list[str]:
    """A scroll area that cannot scroll sideways must not hold content wider than its viewport."""
    found = []
    for area in root.findChildren(QAbstractScrollArea):
        if not area.isVisibleTo(root) or area.widget() is None if hasattr(area, "widget") else True:
            continue
        if area.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
            inner, view = area.widget().width(), area.viewport().width()
            if inner > view + 1:
                found.append(f"{label(area)} holds content {inner}px wide in a {view}px viewport")
    return found


def search_icons(root: QWidget) -> list[str]:
    """The magnifier is centred in its field (within 1 px) and stays clear of the text."""
    found = []
    for field in root.findChildren(SearchField):
        if not field.isVisibleTo(root):
            continue
        icon = field.icon_rect()
        if abs(icon.center().y() - (field.height() - 1) / 2) > 1:
            found.append(f"search field {field.placeholderText()!r}: icon centre {icon.center().y()} vs field {field.height() / 2}")
        text_left = field.textMargins().left() + 12  # the style sheet's left padding
        if icon.right() >= text_left:
            found.append(f"search field {field.placeholderText()!r}: the icon overlaps the text")
        if icon.left() != SearchField.LEFT:
            found.append(f"search field {field.placeholderText()!r}: inconsistent left padding")
    return found


def pill_fits(root: QWidget) -> list[str]:
    """The connection pill elides its text; what it shows must fit and the full text stays in its tooltip."""
    pill = root.connection_label
    shown_text = pill.shown_text() if hasattr(pill, "shown_text") else pill.text()
    need = pill.fontMetrics().horizontalAdvance(shown_text) + 46
    found = [] if need <= pill.width() + SLACK else [f"pill shows {shown_text!r}: needs {need}px, has {pill.width()}"]
    if shown_text != pill.text() and pill.text() not in pill.toolTip():
        found.append("an elided pill must carry its full text as a tooltip")
    return found


def audit(w: MainWindow) -> dict[str, list[str]]:
    return {"siblings": sibling_overlaps(w), "squeezed": squeezed(w), "spilled": spilled(w),
            "cards": param_cards(w), "pill": pill_fits(w), "search": search_icons(w),
            "scroll": scroll_content_clipped(w),
            "clipped": [c for c in clipped(w) if not c.startswith("ConnectionPill")]}


def problems(report: dict[str, list[str]]) -> list[str]:
    return [f"{kind}: {line}" for kind, lines in report.items() for line in lines]


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("state", STATES)
def test_nothing_overlaps_squeezes_or_spills(qtbot, monkeypatch, catalog, tmp_path, themed, state, size):
    w = build(qtbot, monkeypatch, catalog, tmp_path, state)
    settle(qtbot, w, size)
    assert problems(audit(w)) == []


def test_the_parameter_cards_of_gt_geq_7_keep_their_parts_apart_at_the_minimum(qtbot, monkeypatch, catalog, tmp_path,
                                                                            themed):
    w = build(qtbot, monkeypatch, catalog, tmp_path, "gt-geq-7")
    settle(qtbot, w, (1280, 760))
    cards = [r for r in w.params.rows() if r.isVisibleTo(w)]
    assert len(cards) == 8  # 7 bands and VOL
    assert param_cards(w) == []
    assert w.params._grid_scroll.viewport().height() >= max(c.minimumSizeHint().height() for c in cards)  # not squeezed away
    assert all(c.width() >= c.minimumSizeHint().width() and c.height() >= c.minimumSizeHint().height() for c in cards)


def test_there_is_no_effects_button_in_the_bar_at_any_width(qtbot, monkeypatch, catalog, tmp_path, themed):
    from PySide6.QtWidgets import QAbstractButton

    w = build(qtbot, monkeypatch, catalog, tmp_path, "no-patch")
    for size in SIZES:
        settle(qtbot, w, size)
        assert not hasattr(w, "effects_button")
        assert not [b for b in w.header.findChildren(QAbstractButton) if "efectos" in (b.text() + b.accessibleName()).lower()]


def test_every_search_field_has_a_centred_magnifier(qtbot, monkeypatch, catalog, tmp_path, themed):
    w = build(qtbot, monkeypatch, catalog, tmp_path, "no-patch")
    settle(qtbot, w, (1280, 760))
    fields = [w.catalog_panel.search, w.effects_panel.search, w.bank_panel.search]
    assert all(isinstance(f, SearchField) for f in fields)
    for field in fields:
        icon = field.icon_rect()
        assert abs(icon.center().y() - (field.height() - 1) / 2) <= 1


def test_the_save_and_discard_buttons_fit_the_header_at_every_size(qtbot, monkeypatch, catalog, tmp_path, themed):
    w = build(qtbot, monkeypatch, catalog, tmp_path, "gt-geq-7")
    w.rename_patch("Edited")  # dirty: the status chip and both buttons show together
    for size in SIZES:
        settle(qtbot, w, size)
        for button in (w.save_button, w.discard_button):
            assert button.isVisibleTo(w) and button.width() >= 40 and button.text() == ""
            assert button.accessibleName() and button.toolTip()
        assert problems(audit(w)) == []
