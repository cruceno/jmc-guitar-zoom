"""Render the app icon (SVG) to ``packaging/icons/app-icon.png`` (256 px) and ``app-icon.ico``.

Run offscreen: ``QT_QPA_PLATFORM=offscreen uv run python packaging/make_icons.py``. The ICO holds PNG frames of
16, 32, 48, 64, 128 and 256 px (the PNG-in-ICO form every Windows since Vista reads)."""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "jmc_guitar_zoom" / "ui" / "design" / "app-icon.svg"
OUT = ROOT / "packaging" / "icons"
ICO_SIZES = (16, 32, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def build_ico(frames: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries, blobs = b"", b""
    for size, png in frames:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    return header + entries + blobs


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"invalid SVG: {SVG}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    big = render(renderer, 256)
    (OUT / "app-icon.png").write_bytes(png_bytes(big))
    frames = [(s, png_bytes(render(renderer, s))) for s in ICO_SIZES]
    (OUT / "app-icon.ico").write_bytes(build_ico(frames))
    print(f"wrote {OUT / 'app-icon.png'} and {OUT / 'app-icon.ico'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
