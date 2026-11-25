"""The memory bars (top bar and effects screen) are coloured by FREE bytes, with a word and an icon besides colour."""
import pytest
from PySide6.QtGui import QColor

from test_ui_effects_manager import BEFORE, PedalFiles, connected_window, open_screen
from test_ui_install_indicators import REAL_READ, asks
from ui_replies import FIXTURES
from jmc_guitar_zoom.effects import flst
from jmc_guitar_zoom.effects.catalog import load_catalog
from jmc_guitar_zoom.ui import memory, tokens
from jmc_guitar_zoom.ui import strings as ST
from jmc_guitar_zoom.ui.main_window import MainWindow

from fixture_files import EFFECTS  # noqa: E402


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"), ("Guitar Lab", EFFECTS / "lib"))


@pytest.fixture(autouse=True)
def reads_the_effect_list(monkeypatch):
    monkeypatch.setattr(MainWindow, "_load_installed_state", REAL_READ)


BOUNDARIES = [(159_999, "low"), (160_000, "ok"), (63_999, "critical"), (64_000, "low"), (0, "critical"),
              (3_087_950, "ok")]


@pytest.mark.parametrize("free,state", BOUNDARIES)
def test_each_state_at_its_boundaries(free, state):
    assert memory.memory_state(free) == state
    assert memory.MEMORY_OK_FREE == 160_000 and memory.MEMORY_LOW_FREE == 64_000


def screen(qtbot, monkeypatch, catalog, tmp_path, free, opened=True):
    files = PedalFiles(BEFORE, free=free)
    w = connected_window(qtbot, monkeypatch, catalog, tmp_path, files)
    qtbot.waitUntil(lambda: w.effect_installed(0x9000030) is not None, timeout=5000)
    return w, (open_screen(qtbot, w) if opened else None), files


@pytest.mark.parametrize("free,state", BOUNDARIES[:4])
def test_both_bars_show_the_state_with_a_word_an_icon_a_tooltip_and_an_accessible_name(
        qtbot, monkeypatch, catalog, tmp_path, free, state):
    w, panel, _files = screen(qtbot, monkeypatch, catalog, tmp_path, free)
    word = {"low": "Memoria baja", "critical": "Memoria crítica"}[state] if state != "ok" else ""
    assert ST.MEMORY_LOW == "Memoria baja" and ST.MEMORY_CRITICAL == "Memoria crítica"
    w._set_header_level(0)  # the default test window is compact: show the top bar with all its words
    tip = ST.memory_state_tip(state, free)
    assert f"{free:,}".replace(",", ".") in tip  # the exact free bytes
    for bar, flag, icon, value in ((w.memory_bar, w.memory_word, w.memory_icon, w.memory_value),
                                   (panel.memory_bar, panel.memory_flag, panel.memory_icon, panel.memory_label)):
        assert bar.property("memory") == state
        assert flag.text() == word and (not flag.isHidden()) == bool(word)
        assert (not icon.isHidden()) == bool(word)
        for widget in (bar, value):
            assert widget.toolTip() == tip or tip in widget.toolTip()
        assert bar.accessibleName() == tip
        if word:
            assert flag.accessibleName() == word and icon.accessibleName() == word
            assert icon.toolTip() == tip and flag.toolTip() == tip


def test_the_compact_top_bar_keeps_the_icon_and_the_percentage_when_the_word_does_not_fit(qtbot, monkeypatch, catalog, tmp_path):
    w, _panel, _files = screen(qtbot, monkeypatch, catalog, tmp_path, 100_000, opened=False)
    w._set_header_level(1)
    assert w.memory_word.isHidden() and not w.memory_icon.isHidden() and not w.memory_value.isHidden()
    assert w.memory_value.text().endswith("%")
    w._set_header_level(0)
    assert not w.memory_word.isHidden()


def test_the_state_follows_an_install_and_a_remove(qtbot, monkeypatch, catalog, tmp_path):
    asks(monkeypatch)
    w, panel, files = screen(qtbot, monkeypatch, catalog, tmp_path, 160_100)
    assert w.memory_bar.property("memory") == "ok" and panel.memory_bar.property("memory") == "ok"
    panel.select_effect("MDL_12ST.ZD2")
    panel.install_button.click()  # the upload takes the memory below 160 000 bytes
    qtbot.waitUntil(lambda: flst.is_installed(files.files[flst.FLST_NAME], "MDL_12ST.ZD2"), timeout=5000)
    qtbot.waitUntil(lambda: w.memory_bar.property("memory") == "low", timeout=5000)
    assert files.free < 160_000 and panel.memory_bar.property("memory") == "low" and panel.memory_flag.text() == "Memoria baja"
    files.free = 160_000 - 64  # a removal gives 64 bytes back (the fake pedal files are 64 bytes)
    panel.select_effect("COMP.ZD2")
    panel.remove_button.click()
    qtbot.waitUntil(lambda: w.memory_bar.property("memory") == "ok", timeout=5000)
    assert panel.memory_bar.property("memory") == "ok" and w.memory_word.isHidden() and panel.memory_flag.isHidden()


def luminance(c: QColor) -> float:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def over(top: QColor, base: QColor) -> QColor:
    a = top.alphaF()
    return QColor(*(round(top.getRgb()[i] * a + base.getRgb()[i] * (1 - a)) for i in range(3)))


def contrast(a: QColor, b: QColor) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("state", ["ok", "low", "critical"])
def test_the_fill_reaches_3_to_1_against_the_track_in_every_state(state):
    track = over(tokens.color("input-bg"), tokens.color("surface-raised"))  # the track sits on a raised surface
    for name in memory.FILL_TOKENS[state]:
        assert contrast(tokens.color(name), track) >= 3.0, name
    qss = (memory.__file__.rsplit("/", 1)[0] + "/design/style.qss")
    text = open(qss, encoding="utf-8").read()
    if state != "ok":  # the stylesheet paints the chunk with those same tokens
        assert f'QProgressBar[memory="{state}"]::chunk' in text
        assert "$" + memory.FILL_TOKENS[state][0].replace("-", "_") in text.split(f'QProgressBar[memory="{state}"]::chunk')[1].split("}")[0]
