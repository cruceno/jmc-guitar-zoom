"""Dark Fusion palette, QSS and per-group colours, all derived from ``design/tokens.json``."""

from __future__ import annotations

import zlib
from string import Template

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import tokens

QSS_PATH = tokens.DESIGN_DIR / "style.qss"


def group_color(group: str) -> QColor:
    """Stable colour for an effect group (known groups from the tokens, hashed otherwise)."""
    known = tokens.group_colors(group)
    if known:
        return known[0]
    return QColor.fromHsv(zlib.crc32(group.encode()) % 360, 140, 170)


def group_text_color(group: str) -> QColor:
    known = tokens.group_colors(group)
    return known[1] if known else group_color(group).lighter(150)


def group_fill_color(group: str) -> QColor:
    known = tokens.group_colors(group)
    return known[2] if known else group_color(group).darker(300)


def render_qss() -> str:
    """The style sheet with every ``$token`` replaced (a missing token raises ``KeyError``)."""
    return Template(QSS_PATH.read_text(encoding="utf-8")).substitute(tokens.qss_mapping())


def build_palette() -> QPalette:
    c = tokens.color
    p = QPalette()
    role = QPalette.ColorRole
    colors = {
        role.Window: c("surface-page"), role.WindowText: c("text-primary"), role.Base: c("surface-sunken"),
        role.AlternateBase: c("surface-raised"), role.ToolTipBase: c("surface-overlay"),
        role.ToolTipText: c("text-primary"), role.Text: c("text-primary"), role.Button: c("surface-control"),
        role.ButtonText: c("text-primary"), role.BrightText: c("status-danger"), role.Link: c("accent-text"),
        role.Highlight: c("surface-selected"), role.HighlightedText: c("text-primary"),
        role.PlaceholderText: c("text-tertiary"),
    }
    for r, col in colors.items():
        p.setColor(r, col)
    disabled = QPalette.ColorGroup.Disabled
    for r in (role.Text, role.ButtonText, role.WindowText):
        p.setColor(disabled, r, c("text-disabled"))
    return p


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setStyleSheet(render_qss())
