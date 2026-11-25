import re
from pathlib import Path

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QWidget

from jmc_guitar_zoom.ui import theme, tokens


def luminance(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    hi, lo = sorted((luminance(tokens.color(a)), luminance(tokens.color(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_every_template_token_resolves():
    qss = theme.render_qss()
    assert "$" not in qss and "None" not in qss


def test_style_sheet_parses_without_warnings(qtbot):
    seen = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: seen.append(msg) if mode != QtMsgType.QtDebugMsg else None)
    try:
        w = QWidget()
        qtbot.addWidget(w)
        w.setStyleSheet(theme.render_qss())
        w.ensurePolished()
    finally:
        qInstallMessageHandler(previous)
    assert not [m for m in seen if "stylesheet" in m.lower() or "parse" in m.lower()]


def test_text_tokens_reach_4_5_on_every_surface():
    surfaces = ["surface-sunken", "surface-page", "surface-raised", "surface-overlay", "surface-control"]
    for text in ("text-primary", "text-secondary", "text-tertiary", "text-disabled"):
        for surface in surfaces:
            assert contrast(text, surface) >= 4.5, (text, surface)
    assert contrast("on-accent", "accent") >= 4.5
    assert contrast("border-strong", "surface-page") >= 3


def test_group_tokens_keep_their_meaning_and_contrast():
    for group in ("DYNAMICS", "FILTER", "DRIVE", "AMP", "PREAMP", "BASS AMP", "CABINET", "AG MODEL",
                  "MODULATION", "SFX", "DELAY", "REVERB", "PEDAL"):
        key = "group-" + tokens.group_key(group)
        assert theme.group_color(group) == tokens.color(key)
        assert contrast(key + "-text", key + "-fill") >= 4.5, group
        assert contrast(key, "surface-page") >= 3, group
    assert theme.group_color("Mystery") == theme.group_color("Mystery")  # hashed, stable


def test_control_icons_use_token_colours():
    icons = Path(tokens.DESIGN_DIR / "icons")
    for name, token in (("chevron-up", "text-primary"), ("chevron-down", "text-primary"), ("check", "on-accent")):
        stroke = re.search(r'stroke="(#[0-9a-f]{6})"', (icons / f"{name}.svg").read_text())[1]
        assert stroke == tokens.color(token).name(), name
