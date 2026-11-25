"""Card painters for list items: patch cards (the effect cards of the catalog and the knobs follow)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QDial, QStyle, QStyledItemDelegate

from . import strings as S
from . import tokens
from .fonts import display_font, ui_font
from .glass import paint_glow
from .theme import group_color, group_fill_color, group_text_color

ROLE_NUMBER = Qt.ItemDataRole.UserRole + 10   # display number of the location (int)
ROLE_NAME = Qt.ItemDataRole.UserRole + 11     # patch name ("" for an empty location)
ROLE_STRIP = Qt.ItemDataRole.UserRole + 12    # [(group, span, enabled)] per effect; None for an empty location
ROLE_DIRTY = Qt.ItemDataRole.UserRole + 13    # unsaved edits (bool)

CARD_HEIGHT = 56
SLOT_WIDTH = 16


def card_path(rect: QRectF, radius: float = 12) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def with_alpha(color: QColor, alpha: float) -> QColor:
    out = QColor(color)
    out.setAlphaF(alpha)
    return out


class PatchCardDelegate(QStyledItemDelegate):
    """A patch as a card: number badge, name, a strip with one block per effect and an edited/empty chip."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(option.rect.width(), CARD_HEIGHT)

    def paint(self, p: QPainter, option, index) -> None:
        strip = index.data(ROLE_STRIP)
        empty = strip is None
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 3, -4, -3)
        path = card_path(rect)
        if selected:
            paint_glow(p, rect, "glow-accent", 12, 3)
        if empty:
            pen = QPen(tokens.color("border-control"), 1.2, Qt.PenStyle.DashLine)
        else:
            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if selected:
                fill.setColorAt(0, with_alpha(tokens.color("card-selected"), 0.28))
                fill.setColorAt(1, with_alpha(tokens.color("card-selected"), 0.12))
            else:
                fill.setColorAt(0, tokens.color("card-hover" if hover else "card-top"))
                fill.setColorAt(1, tokens.color("card-bottom"))
            p.fillPath(path, fill)
            pen = QPen(with_alpha(tokens.color("accent"), 0.6) if selected else tokens.color("card-rim"), 1.5 if selected else 1)
        p.setPen(pen)
        p.drawPath(path)

        badge = QRectF(rect.left() + 10, rect.center().y() - 15, 30, 30)
        badge_path = card_path(badge, 9)
        p.fillPath(badge_path, tokens.color("accent") if selected else tokens.color("input-bg"))
        p.setPen(tokens.color("on-accent") if selected else tokens.color("text-secondary"))
        p.setFont(ui_font(13, ui_font().Weight.Medium))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(index.data(ROLE_NUMBER) or ""))

        text_left = badge.right() + 12
        chip = S.EMPTY if empty else (S.EDITED if index.data(ROLE_DIRTY) else "")
        chip_font = ui_font(12)
        chip_w = QFontMetrics(chip_font).horizontalAdvance(chip) + 18 if chip else 0
        name_font = ui_font(15)
        p.setFont(name_font)
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        p.setPen(brush.color() if brush is not None else tokens.color("text-primary"))
        name = index.data(ROLE_NAME) or (S.EMPTY if empty else S.UNNAMED)
        name_rect = QRectF(text_left, rect.top() + 7, rect.right() - text_left - chip_w - 14, 20)
        p.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(name_font).elidedText(name, Qt.TextElideMode.ElideRight, int(name_rect.width())))
        if chip:
            warn = tokens.color("status-warn") if not empty else tokens.color("text-tertiary")
            chip_rect = QRectF(rect.right() - chip_w - 8, rect.top() + 8, chip_w, 18)
            p.setPen(QPen(with_alpha(warn, 0.7), 1))
            p.drawPath(card_path(chip_rect, 9))
            p.setFont(chip_font)
            p.setPen(warn)
            p.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, chip)

        x, y = text_left, rect.bottom() - 13
        for group, span, enabled in (strip or []):
            w = span * SLOT_WIDTH - 3
            if x + w > rect.right() - 8:
                break
            block = QRectF(x, y, w, 5)
            if group is None:
                p.setPen(QPen(tokens.color("border-control"), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(with_alpha(group_color(group), 1.0 if enabled else 0.4))
            p.drawRoundedRect(block, 2.5, 2.5)
            x += span * SLOT_WIDTH
        p.restore()


class Knob(QDial):
    """Painted knob: 270 degree track, accent value arc, pointer, default tick and the value in the middle."""

    def __init__(self) -> None:
        super().__init__()
        self.default_value = 0
        self.setFixedSize(QSize(72, 72))
        self.setNotchesVisible(False)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        from math import cos, radians, sin

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = min(self.width(), self.height()) / 2 - 6
        span = max(1, self.maximum() - self.minimum())
        frac = (self.value() - self.minimum()) / span
        face = QRadialGradient(c - QPointF(r * 0.35, r * 0.4), r * 1.5)
        face.setColorAt(0, QColor(255, 255, 255, 41))
        face.setColorAt(1, QColor(0, 0, 0, 90))
        p.setBrush(face)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, r - 5, r - 5)
        arc = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(tokens.color("knob-arc-track"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc, 225 * 16, -270 * 16)
        if frac > 0:
            p.setPen(QPen(tokens.color("knob-arc-value"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc, 225 * 16, round(-270 * frac * 16))
        tick = radians(225 - 270 * (self.default_value - self.minimum()) / span)
        p.setPen(QPen(tokens.color("knob-default-tick"), 1.5))
        p.drawLine(QPointF(c.x() + cos(tick) * (r + 1), c.y() - sin(tick) * (r + 1)),
                   QPointF(c.x() + cos(tick) * (r + 4), c.y() - sin(tick) * (r + 4)))
        ang = radians(225 - 270 * frac)
        p.setPen(QPen(tokens.color("knob-indicator"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c.x() + cos(ang) * (r - 14), c.y() - sin(ang) * (r - 14)),
                   QPointF(c.x() + cos(ang) * (r - 7), c.y() - sin(ang) * (r - 7)))
        p.setPen(tokens.color("text-primary"))
        p.setFont(display_font(16, 500))
        p.drawText(QRectF(c.x() - 20, c.y() - 11, 40, 22), Qt.AlignmentFlag.AlignCenter, str(self.value()))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(tokens.color("focus-ring"), 2))
            p.drawEllipse(c, r + 3, r + 3)


ROLE_EFFECT = Qt.ItemDataRole.UserRole + 20  # {"name", "group", "dsp", "wide", "installed", "blocked", "in_chain"}


class EffectCardDelegate(QStyledItemDelegate):
    """A catalog effect as a card: group monogram, name, group and slots, DSP and one badge."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(option.rect.width(), 60)

    def paint(self, p: QPainter, option, index) -> None:
        d = index.data(ROLE_EFFECT)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 3, -2, -3)
        path = card_path(rect)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if selected:
            fill.setColorAt(0, with_alpha(tokens.color("card-selected"), 0.28))
            fill.setColorAt(1, with_alpha(tokens.color("card-selected"), 0.12))
        else:
            fill.setColorAt(0, tokens.color("card-hover" if hover else "card-top"))
            fill.setColorAt(1, tokens.color("card-bottom"))
        p.fillPath(path, fill)
        p.setPen(QPen(with_alpha(tokens.color("accent"), 0.6) if selected else tokens.color("card-rim"), 1.5 if selected else 1))
        p.drawPath(path)
        group = d["group"]
        mono = QRectF(rect.left() + 10, rect.center().y() - 21, 30, 42)
        p.setBrush(group_fill_color(group))
        p.setPen(QPen(group_color(group), 1.5))
        p.drawRoundedRect(mono, 7, 7)
        p.setPen(group_text_color(group))
        p.setFont(display_font(12, 600))
        p.drawText(mono, Qt.AlignmentFlag.AlignCenter, d["name"][:2].upper())
        left = mono.right() + 12
        right = rect.right() - 12
        dsp_font = ui_font(14)
        dsp = S.percent(d["dsp"])
        dsp_w = QFontMetrics(dsp_font).horizontalAdvance(dsp)
        p.setFont(ui_font(15))
        p.setPen(tokens.color("text-primary"))
        name_rect = QRectF(left, rect.top() + 6, right - left - dsp_w - 8, 20)
        p.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(ui_font(15)).elidedText(d["name"], Qt.TextElideMode.ElideRight, int(name_rect.width())))
        p.setFont(dsp_font)
        p.setPen(tokens.color("text-secondary"))
        p.drawText(QRectF(right - dsp_w, rect.top() + 6, dsp_w, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, dsp)
        p.setFont(ui_font(12))
        p.setPen(group_text_color(group))
        p.drawText(QRectF(left, rect.top() + 29, 170, 18), Qt.AlignmentFlag.AlignVCenter,
                   f"{S.group_label(group)} · {S.slots_label(2 if d['wide'] else 1)}")
        badge = (S.BADGE_NOT_A1, "status-danger") if d["blocked"] else (
            (S.BADGE_IN_CHAIN, "accent") if d["in_chain"] else (
                (S.BADGE_ON_PEDAL, "text-secondary") if d["installed"] else None))
        if badge:
            text, token = badge
            w = QFontMetrics(ui_font(11)).horizontalAdvance(text) + 14
            chip = QRectF(right - w, rect.top() + 30, w, 16)
            p.setPen(QPen(with_alpha(tokens.color(token), 0.7), 1))
            p.drawPath(card_path(chip, 8))
            p.setFont(ui_font(11))
            p.setPen(tokens.color(token))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()
