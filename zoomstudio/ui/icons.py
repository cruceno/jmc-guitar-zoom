"""Line icons (24 px grid) drawn from the paths of the approved prototype, in any token colour."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import tokens

PATHS = {
    "sliders": '<path d="M5 4v16M12 4v16M19 4v16"/><circle cx="5" cy="9" r="2"/><circle cx="12" cy="15" r="2"/><circle cx="19" cy="8" r="2"/>',
    "power": '<path d="M12 3v8"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
    "save": '<path d="M12 3v11"/><path d="m7 9 5 5 5-5"/><path d="M5 17v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "chev": '<path d="m6 9 6 6 6-6"/>',
    "up": '<path d="m7 15 5-5 5 5"/>',
    "tuner": '<path d="M9 3v7a3 3 0 0 0 6 0V3"/><path d="M12 13v8"/>',
    "filesave": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11v6"/><path d="m9 14 3 3 3-3"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "reload": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "plug": '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
    "unplug": '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/><path d="M3 3l18 18"/>',
    "target": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    "swap": '<path d="M4 8h14l-3-3"/><path d="M20 16H6l3 3"/>',
    "package": '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "arrowUp": '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
    "arrowDown": '<path d="M12 5v14"/><path d="m18 13-6 6-6-6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.3"/>',
    "ban": '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
    "reset": '<path d="M4 12a8 8 0 1 0 2.3-5.7"/><path d="M4 4v5h5"/>',
    "tri": '<path d="M12 6 5 17h14z" fill="currentColor" stroke="none"/>',
    "library": '<path d="M4 4h4v16H4zM10 4h4v16h-4z"/><path d="m16 5 3.5-1 3 15.5-3.5.8z"/>',
    "dialog": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10h10M7 14h6"/>',
}
PATHS["close"] = PATHS["x"]



@lru_cache(maxsize=256)
def pixmap(name: str, color_hex: str, size: int = 20, dpr: float = 1.0) -> QPixmap:
    body = PATHS[name].replace("currentColor", color_hex)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color_hex}" '
           f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    px = round(size * dpr)
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(dpr)
    return result


def icon(name: str, token: str = "text-primary", size: int = 20) -> QIcon:
    """Icon in a token colour with a disabled variant (``text-disabled``)."""
    out = QIcon()
    out.addPixmap(pixmap(name, tokens.color(token).name(), size), QIcon.Mode.Normal)
    out.addPixmap(pixmap(name, tokens.color("text-disabled").name(), size), QIcon.Mode.Disabled)
    return out


def colored(name: str, color: QColor, size: int = 20) -> QPixmap:
    return pixmap(name, color.name(), size)

