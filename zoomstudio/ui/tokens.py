"""Design tokens of the app: one JSON file read once, exposed to the palette, the QSS and the painters."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QColor

DESIGN_DIR = Path(__file__).with_name("design")
_RGBA = re.compile(r"rgba\((\d+),(\d+),(\d+),([0-9.]+)\)")


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads((DESIGN_DIR / "tokens.json").read_text(encoding="utf-8"))


def parse_color(value: str) -> QColor:
    """``#rrggbb`` or ``rgba(r,g,b,a)`` with ``a`` in 0..1."""
    m = _RGBA.fullmatch(value)
    if m:
        return QColor(int(m[1]), int(m[2]), int(m[3]), round(float(m[4]) * 255))
    return QColor(value)


def color(name: str) -> QColor:
    return parse_color(_data()["color"][name])


def color_names() -> list[str]:
    return list(_data()["color"])


def qss_color(name: str) -> str:
    """Colour as QSS writes it (QSS wants alpha as 0..255)."""
    c = color(name)
    if c.alpha() == 255:
        return c.name()
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"


def px(name: str) -> int:
    return int(_data()["dimension"][name])


def font_families(name: str) -> list[str]:
    """Family names of a font stack token, generic families dropped (``font-sans``, ``font-display``)."""
    parts = [p.strip().strip('"') for p in _data()["font"][name].split(",")]
    return [p for p in parts if p not in ("sans-serif", "system-ui", "monospace", "ui-monospace")]


def group_key(group: str) -> str:
    return group.strip().lower().replace(" ", "-")


def group_colors(group: str) -> tuple[QColor, QColor, QColor] | None:
    """(border/swatch, text, fill) of an effect group, ``None`` for a group without tokens."""
    key = group_key(group)
    if f"group-{key}" not in _data()["color"]:
        return None
    return color(f"group-{key}"), color(f"group-{key}-text"), color(f"group-{key}-fill")


def qss_mapping() -> dict[str, str]:
    """Every token as a ``string.Template`` field of the QSS (hyphens become underscores)."""
    out = {n.replace("-", "_"): qss_color(n) for n in color_names()}
    out.update({n.replace("-", "_"): str(v) for n, v in _data()["dimension"].items()})
    out["control_radius"] = str(px("control-height") // 2)
    out["font_sans"] = ", ".join(f'"{f}"' for f in font_families("font-sans")) + ", sans-serif"
    out["font_display"] = ", ".join(f'"{f}"' for f in font_families("font-display")) + ", sans-serif"
    out["icons_dir"] = (DESIGN_DIR / "icons").as_posix()
    return out
