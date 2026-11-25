from PySide6.QtCore import QCoreApplication, QLocale
from PySide6.QtGui import QFontDatabase, QFontMetrics

from zoomstudio.ui import fonts


def test_bundled_families_are_registered_with_the_weights_the_design_uses(qapp):
    families = fonts.register_fonts()
    assert "Exo 2" in families and "Roboto" in families
    width = lambda w: QFontMetrics(fonts.display_font(40, w)).horizontalAdvance("Hall Reverb 53")  # noqa: E731
    assert width(300) < width(500) < width(600)  # the variable font answers to its weight axis
    assert {"Regular", "Medium", "Bold"} <= set(QFontDatabase.styles("Roboto"))


def test_fonts_ship_with_their_licences():
    assert (fonts.FONTS_DIR / "OFL.txt").read_text().startswith("Copyright 2013 The Exo 2 Project Authors")
    assert "Apache License" in (fonts.FONTS_DIR / "LICENSE-Roboto.txt").read_text()


def test_qt_spanish_translations_load(qapp):
    assert fonts.install_spanish(QCoreApplication.instance())
    assert QLocale().language() == QLocale.Language.Spanish


def test_display_and_ui_fonts_use_the_token_stacks(qapp):
    fonts.register_fonts()
    assert fonts.display_font(40).families()[0] == "Exo 2"
    assert fonts.ui_font().families()[0] == "Roboto" and fonts.ui_font().pixelSize() == 15
