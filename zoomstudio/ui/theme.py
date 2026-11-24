"""Dark Fusion palette and per-group colours."""

from __future__ import annotations

import zlib

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_GROUP_COLORS = {
    "DYNAMICS": "#b8860b",
    "FILTER": "#2e8b8b",
    "DRIVE": "#c0392b",
    "AMP": "#d35400",
    "PREAMP": "#a0522d",
    "BASS AMP": "#8e5a2b",
    "CABINET": "#7f6a4f",
    "AG MODEL": "#6b8e23",
    "MODULATION": "#2980b9",
    "SFX": "#8e44ad",
    "DELAY": "#27ae60",
    "REVERB": "#3b5bdb",
    "PEDAL": "#7f8c8d",
}


def group_color(group: str) -> QColor:
    """Stable colour for an effect group (known groups first, hashed otherwise)."""
    known = _GROUP_COLORS.get(group.upper())
    if known:
        return QColor(known)
    return QColor.fromHsv(zlib.crc32(group.encode()) % 360, 140, 170)


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    role = QPalette.ColorRole
    colors = {
        role.Window: "#2b2d31", role.WindowText: "#e6e6e6", role.Base: "#1f2023",
        role.AlternateBase: "#2b2d31", role.ToolTipBase: "#3a3d42", role.ToolTipText: "#e6e6e6",
        role.Text: "#e6e6e6", role.Button: "#383b40", role.ButtonText: "#e6e6e6",
        role.BrightText: "#ff5555", role.Link: "#5aa9ff", role.Highlight: "#3b78c9",
        role.HighlightedText: "#ffffff", role.PlaceholderText: "#8a8d93",
    }
    for r, c in colors.items():
        p.setColor(r, QColor(c))
    disabled = QPalette.ColorGroup.Disabled
    for r in (role.Text, role.ButtonText, role.WindowText):
        p.setColor(disabled, r, QColor("#6c6f75"))
    app.setPalette(p)
