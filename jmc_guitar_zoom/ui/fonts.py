"""Bundled fonts (Exo 2 for display text, Roboto for the interface) and the Qt Spanish translations."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QFont, QFontDatabase

from . import tokens

FONTS_DIR = tokens.DESIGN_DIR / "fonts"
_registered: list[str] = []
_translators: list[QTranslator] = []


def register_fonts() -> list[str]:
    """Register every bundled font with Qt once; returns the families found."""
    if not _registered:
        for path in sorted(FONTS_DIR.glob("*.ttf")):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                _registered.extend(f for f in QFontDatabase.applicationFontFamilies(font_id) if f not in _registered)
    return list(_registered)


def _font(families: list[str], px: int, weight: QFont.Weight) -> QFont:
    font = QFont()
    font.setFamilies(families)
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def ui_font(px: int | None = None, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return _font(tokens.font_families("font-sans"), px or tokens.px("text-body-size"), weight)


def display_font(px: int, weight: int = 500) -> QFont:
    """Exo 2 at a CSS weight (300 Light, 500 Medium, 600 SemiBold). The bundled file is a variable font, so the
    weight goes through its ``wght`` axis: ``QFont.setWeight`` and QSS ``font-weight`` do not reach it."""
    font = _font(tokens.font_families("font-display"), px, QFont.Weight.Normal)
    font.setVariableAxis(QFont.Tag("wght"), weight)
    return font


def install_spanish(app: QCoreApplication | None = None) -> bool:
    """Make Qt's own texts (file dialog, field menus, standard buttons) Spanish; True when found."""
    QLocale.setDefault(QLocale("es"))
    translator = QTranslator()
    found = translator.load(QLocale("es"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    if found:
        (app or QCoreApplication.instance()).installTranslator(translator)
        _translators.append(translator)
    return found
