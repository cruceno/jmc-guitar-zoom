import pytest
from PySide6.QtGui import QColor
from PySide6.QtCore import QSize

from test_ui_theme import luminance
from ui_replies import FIXTURES
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.ui import tokens
from zoomstudio.ui.glass import Backdrop, BackdropRoot, GlassPanel
from zoomstudio.ui.main_window import MainWindow


def test_backdrop_is_built_once_per_size():
    b = Backdrop()
    assert b.ensure(QSize(800, 600)) and not b.ensure(QSize(800, 600))
    assert b.builds == 1 and b.blurred.size() == b.image.size() == QSize(800, 600)
    assert b.ensure(QSize(900, 600)) and b.builds == 2


def test_resizing_is_debounced(qtbot):
    root = BackdropRoot()
    qtbot.addWidget(root)
    root.resize(600, 400)
    root.show()
    built = root.backdrop.builds
    for w in range(610, 650, 8):
        root.resize(w, 400)
    qtbot.waitUntil(lambda: root.backdrop.size == QSize(642, 400), timeout=2000)
    assert root.backdrop.builds - built == 1


def test_panel_paints_tint_over_the_softened_backdrop(qtbot):
    root = BackdropRoot()
    qtbot.addWidget(root)
    root.resize(400, 300)
    panel = GlassPanel(root)
    panel.setParent(root)
    panel.setGeometry(50, 50, 200, 150)
    root.show()
    pixel = panel.grab().toImage().pixelColor(100, 75)
    assert pixel.alpha() == 255 and abs(pixel.value() - tokens.color("glass-tint").value()) < 24


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"))


def test_main_window_uses_painted_glass_only(qtbot, catalog):
    w = MainWindow(catalog)
    qtbot.addWidget(w)
    panels = w.findChildren(GlassPanel)
    assert len(panels) >= 4 and all(p.graphicsEffect() is None for p in panels)
    assert w.size() == QSize(1440, 900) and w.minimumSize() == QSize(1280, 760)


def test_text_keeps_4_5_over_the_brightest_backdrop_point():
    b = Backdrop()
    b.ensure(QSize(1440, 900))
    small = b.blurred.toImage().scaled(96, 60)
    brightest = max((small.pixelColor(x, y) for x in range(96) for y in range(60)), key=luminance)
    for tint in ("glass-tint", "glass-tint-strong", "glass-tint-overlay"):
        t = tokens.color(tint)
        a = t.alphaF()
        base = QColor(round(t.red() * a + brightest.red() * (1 - a)), round(t.green() * a + brightest.green() * (1 - a)),
                      round(t.blue() * a + brightest.blue() * (1 - a)))
        for text in ("text-primary", "text-secondary", "text-tertiary", "text-disabled", "status-danger"):
            hi, lo = sorted((luminance(tokens.color(text)), luminance(base)), reverse=True)
            assert (hi + 0.05) / (lo + 0.05) >= 4.5, (tint, text)
