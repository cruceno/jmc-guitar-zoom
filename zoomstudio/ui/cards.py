"""Card painters for list items: patch cards (the effect cards of the catalog and the knobs follow)."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDial, QListWidget, QListWidgetItem, QMenu, QStyle, QStyledItemDelegate

from . import strings as S
from . import tokens
from .fonts import display_font, ui_font
from .glass import paint_glow
from .theme import group_color, group_fill_color, group_text_color

ROLE_NUMBER = Qt.ItemDataRole.UserRole + 10   # display number of the location (int)
ROLE_NAME = Qt.ItemDataRole.UserRole + 11     # patch name ("" for an empty location)
ROLE_STRIP = Qt.ItemDataRole.UserRole + 12    # [(group, span, enabled)] per effect; None for an empty location
ROLE_DIRTY = Qt.ItemDataRole.UserRole + 13    # unsaved edits (bool)
ROLE_DROP = Qt.ItemDataRole.UserRole + 14     # a drag is over this card and may drop here (bool)
ROLE_META = Qt.ItemDataRole.UserRole + 15     # second line of a bank card: origin and date

STAR = 20  # side of the favourite star of an effect card
STAR_ROOM = STAR + 8  # what the card text gives up at its right edge for it
ROLE_FAV = Qt.ItemDataRole.UserRole + 21  # the effect is a favourite (bool); None: it cannot be one

ROLE_SECTION = Qt.ItemDataRole.UserRole + 31  # (group, count, expanded) on the header row of a section
SECTION_HEIGHT = 36
FAVORITES_KEY = "\0favorites"  # the section (and the filter option) of favourites: no real group has this key

CARD_HEIGHT = 56
SLOT_WIDTH = 16


def card_path(rect: QRectF, radius: float = 12) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


@lru_cache(maxsize=128)
def svg_thumbnail(path: Path, width: int, height: int, dpr: float = 1.0) -> QPixmap | None:
    """An effect's SVG rasterized once at ``width`` x ``height`` (fitted, centred); ``None`` if unreadable."""
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid() or renderer.defaultSize().isEmpty():
        return None
    image = QImage(round(width * dpr), round(height * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    size = renderer.defaultSize().scaled(image.size(), Qt.AspectRatioMode.KeepAspectRatio)
    painter = QPainter(image)
    renderer.render(painter, QRectF((image.width() - size.width()) / 2, (image.height() - size.height()) / 2,
                                    size.width(), size.height()))
    painter.end()
    out = QPixmap.fromImage(image)
    out.setDevicePixelRatio(dpr)
    return out


@lru_cache(maxsize=256)
def pedal_thumbnail(name: str, group: str, width: int, height: int, dpr: float = 1.0) -> QPixmap:
    """A drawn pedal (group colours, three knobs, the name, a footswitch) for effects that have no SVG."""
    image = QImage(round(width * dpr), round(height * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.scale(dpr, dpr)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = QRectF(1.5, 1.5, width - 3, height - 3)
    p.setBrush(group_fill_color(group))
    p.setPen(QPen(group_color(group), 2))
    p.drawRoundedRect(body, 6, 6)
    p.setPen(QPen(group_text_color(group), 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(3):
        p.drawEllipse(QPointF(width * (0.27 + 0.23 * i), height * 0.3), 4.5, 4.5)
    p.setPen(tokens.color("text-primary"))
    p.setFont(display_font(8, 600))
    p.drawText(QRectF(2, height * 0.5, width - 4, 14), Qt.AlignmentFlag.AlignCenter,
               QFontMetrics(display_font(8, 600)).elidedText(name, Qt.TextElideMode.ElideRight, width - 6))
    p.setPen(QPen(group_text_color(group), 1.5))
    p.setBrush(tokens.color("surface-control"))
    p.drawEllipse(QPointF(width / 2, height * 0.8), 7, 7)
    p.end()
    out = QPixmap.fromImage(image)
    out.setDevicePixelRatio(dpr)
    return out


def with_alpha(color: QColor, alpha: float) -> QColor:
    out = QColor(color)
    out.setAlphaF(alpha)
    return out


class PatchCardDelegate(QStyledItemDelegate):
    """A patch as a card: number badge, name, a strip with one block per effect and an edited/empty chip."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(1, CARD_HEIGHT)  # the list stretches a row to its viewport; a real width would add a sideways scrollbar

    def paint(self, p: QPainter, option, index) -> None:
        strip = index.data(ROLE_STRIP)
        empty = strip is None or all(group is None for group, _span, _on in strip)  # no location, or no effect
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
        if index.data(ROLE_DROP):  # the drop target of a drag: an accent frame over a tinted card
            p.fillPath(path, with_alpha(tokens.color("accent"), 0.16))
            p.setPen(QPen(tokens.color("accent"), 2.5))
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
        dirty_chip = chip == S.EDITED
        chip_w = QFontMetrics(chip_font).horizontalAdvance(chip) + 18 + (10 if dirty_chip else 0) if chip else 0
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
            if dirty_chip:  # a warn-coloured dot before the word
                p.setBrush(warn)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(chip_rect.left() + 11, chip_rect.center().y()), 3, 3)
                p.setPen(warn)
                p.drawText(chip_rect.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, chip)
            else:
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


BANK_CARD_HEIGHT = 72


class BankCardDelegate(QStyledItemDelegate):
    """A banked patch as a card: name, «origin · date» and the strip with one block per effect."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(1, BANK_CARD_HEIGHT)

    def paint(self, p: QPainter, option, index) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 3, -4, -3)
        path = card_path(rect)
        if selected:
            paint_glow(p, rect, "glow-accent", 12, 3)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if selected:
            fill.setColorAt(0, with_alpha(tokens.color("card-selected"), 0.28))
            fill.setColorAt(1, with_alpha(tokens.color("card-selected"), 0.12))
        else:
            fill.setColorAt(0, tokens.color("card-hover" if hover else "card-top"))
            fill.setColorAt(1, tokens.color("card-bottom"))
        p.fillPath(path, fill)
        p.setPen(QPen(with_alpha(tokens.color("accent"), 0.6) if selected else tokens.color("card-rim"),
                      1.5 if selected else 1))
        p.drawPath(path)
        left, right = rect.left() + 14, rect.right() - 12
        name_font = ui_font(15)
        p.setFont(name_font)
        p.setPen(tokens.color("text-primary"))
        name = index.data(ROLE_NAME) or S.UNNAMED
        p.drawText(QRectF(left, rect.top() + 7, right - left, 20), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(name_font).elidedText(name, Qt.TextElideMode.ElideRight, int(right - left)))
        meta_font = ui_font(12)
        p.setFont(meta_font)
        p.setPen(tokens.color("text-secondary"))
        meta = index.data(ROLE_META) or ""
        p.drawText(QRectF(left, rect.top() + 28, right - left, 16), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(meta_font).elidedText(meta, Qt.TextElideMode.ElideRight, int(right - left)))
        x, y = left, rect.bottom() - 13
        for group, span, enabled in (index.data(ROLE_STRIP) or []):
            w = span * SLOT_WIDTH - 3
            if x + w > right:
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
        self.setFixedSize(QSize(66, 66))
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


def star_rect(item_rect: QRect) -> QRectF:
    """Where the star of an effect card sits inside the item's rectangle."""
    card = QRectF(item_rect).adjusted(2, 3, -2, -3)
    return QRectF(card.right() - 10 - STAR, card.center().y() - STAR / 2, STAR, STAR)


def paint_star(p: QPainter, rect: QRectF, on: bool, hover: bool = False) -> None:
    """A filled star for a favourite, an outline for an effect that is not (shape, not just colour)."""
    c, outer, inner = rect.center(), rect.width() / 2 - 1, rect.width() / 4.2
    points = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(-90 + 36 * i)
        points.append(QPointF(c.x() + radius * math.cos(angle), c.y() + radius * math.sin(angle)))
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = tokens.color("accent" if on or hover else "text-secondary")
    p.setPen(QPen(color, 1.4))
    p.setBrush(color if on else Qt.BrushStyle.NoBrush)
    p.drawPolygon(QPolygonF(points))
    p.restore()


class FavoriteList(QListWidget):
    """A list of effect cards with a favourite star: a click on it, the F key or the context menu toggle it.

    An item takes part when it carries ``ROLE_FAV`` (True or False); one without it has no star.
    """

    favorite_toggled = Signal(object)  # the item whose star was used

    def _can_favorite(self, item: QListWidgetItem | None) -> bool:
        return item is not None and item.data(ROLE_FAV) is not None

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        item = self.itemAt(event.position().toPoint())
        if (event.button() == Qt.MouseButton.LeftButton and self._can_favorite(item)
                and star_rect(self.visualItemRect(item)).adjusted(-4, -4, 4, 4).contains(event.position())):
            self.favorite_toggled.emit(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.key() == Qt.Key.Key_F and not event.modifiers() and self._can_favorite(self.currentItem()):
            self.favorite_toggled.emit(self.currentItem())
            event.accept()
            return
        super().keyPressEvent(event)

    def context_menu_for(self, item: QListWidgetItem) -> QMenu | None:
        if not self._can_favorite(item):
            return None
        menu = QMenu(self)
        on = bool(item.data(ROLE_FAV))
        action = menu.addAction(S.FAVORITE_REMOVE if on else S.FAVORITE_ADD)
        action.triggered.connect(lambda: self.favorite_toggled.emit(item))
        return menu

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt API)
        menu = self.context_menu_for(self.itemAt(event.pos()))
        if menu is not None:
            menu.exec(event.globalPos())
            event.accept()

    def viewportEvent(self, event) -> bool:  # noqa: N802 (Qt API)
        if event.type() == event.Type.ToolTip:
            item = self.itemAt(event.pos())
            if self._can_favorite(item) and star_rect(self.visualItemRect(item)).contains(event.pos()):
                from PySide6.QtWidgets import QToolTip
                QToolTip.showText(event.globalPos(), S.FAVORITE_REMOVE if item.data(ROLE_FAV) else S.FAVORITE_ADD, self)
                return True
        return super().viewportEvent(event)


def section_label(group: str) -> str:
    return S.FAVORITES if group == FAVORITES_KEY else S.group_label(group)


def set_section_header(header: QListWidgetItem, group: str, count: int, expanded: bool) -> None:
    header.setData(ROLE_SECTION, (group, count, expanded))
    header.setData(Qt.ItemDataRole.AccessibleTextRole, S.effects_section_name(section_label(group), count, expanded))
    header.setToolTip(S.EFFECTS_SECTION_TIP)


def paint_section(p: QPainter, option, section: tuple[str, int, bool]) -> None:
    """A collapsible section header: chevron, group colour (a star for favourites), Spanish label and count."""
    group, count, expanded = section
    hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
    focused = bool(option.state & QStyle.StateFlag.State_Selected)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(option.rect).adjusted(2, 3, -2, -3)
    if hover or focused:
        p.setPen(QPen(tokens.color("accent") if focused else tokens.color("card-rim"), 1.5 if focused else 1))
        p.setBrush(tokens.color("card-hover") if hover else tokens.color("card-top"))
        p.drawRoundedRect(rect, 8, 8)
    cy, x = rect.center().y(), rect.left() + 12
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(tokens.color("text-secondary"))
    if expanded:  # chevron pointing down, or right when collapsed
        p.drawPolygon(QPolygonF([QPointF(x, cy - 3), QPointF(x + 9, cy - 3), QPointF(x + 4.5, cy + 3)]))
    else:
        p.drawPolygon(QPolygonF([QPointF(x + 1, cy - 5), QPointF(x + 1, cy + 5), QPointF(x + 7, cy)]))
    if group == FAVORITES_KEY:
        paint_star(p, QRectF(x + 17, cy - 7, 14, 14), True)
    else:
        p.setBrush(group_color(group))
        p.drawEllipse(QPointF(x + 24, cy), 5, 5)
    count_text = str(count)
    font = ui_font(13, QFont.Weight.DemiBold)
    count_w = QFontMetrics(ui_font(13)).horizontalAdvance(count_text)
    label_rect = QRectF(x + 38, rect.top(), rect.right() - 12 - count_w - 8 - (x + 38), rect.height())
    p.setFont(font)
    p.setPen(tokens.color("accent") if group == FAVORITES_KEY else group_text_color(group))
    p.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter,
               QFontMetrics(font).elidedText(section_label(group), Qt.TextElideMode.ElideRight, int(label_rect.width())))
    p.setFont(ui_font(13))
    p.setPen(tokens.color("text-secondary"))
    p.drawText(QRectF(rect.right() - 12 - count_w, rect.top(), count_w, rect.height()),
               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, count_text)
    p.restore()


class SectionList(FavoriteList):
    """Effect cards grouped in collapsible sections: header rows fold and unfold the cards that follow them.

    A header is a row carrying ``ROLE_SECTION``; click, Enter and Space on it emit ``section_toggled``.
    Folding only hides the member rows, so selection, drag and keyboard navigation keep working.
    """

    section_toggled = Signal(object)  # the header item that was activated

    def __init__(self) -> None:
        super().__init__()
        self.itemClicked.connect(self._on_clicked)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        if item.data(ROLE_SECTION):
            self.section_toggled.emit(item)

    def is_header(self, item: QListWidgetItem | None) -> bool:
        return item is not None and bool(item.data(ROLE_SECTION))

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.is_header(self.currentItem()) and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.section_toggled.emit(self.currentItem())
            event.accept()
            return
        super().keyPressEvent(event)

    def set_section_expanded(self, header: QListWidgetItem, expanded: bool) -> None:
        """Fold or unfold in place (the rows after ``header`` up to the next header)."""
        group, count, _was = header.data(ROLE_SECTION)
        set_section_header(header, group, count, expanded)
        for i in range(self.row(header) + 1, self.count()):
            item = self.item(i)
            if item.data(ROLE_SECTION):
                break
            item.setHidden(not expanded)
        self.viewport().update()


class EffectCardDelegate(QStyledItemDelegate):
    """A catalog effect as a card: group monogram, name, group and slots, DSP and one badge."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(1, SECTION_HEIGHT if index.data(ROLE_SECTION) else 60)  # the list stretches a row to its viewport

    def paint(self, p: QPainter, option, index) -> None:
        if index.data(ROLE_SECTION):
            paint_section(p, option, index.data(ROLE_SECTION))
            return
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
        thumb = svg_thumbnail(d["svg"], 30, 42, 1.0) if d.get("svg") else None
        if thumb is not None:
            p.drawPixmap(mono.toRect(), thumb)
        else:
            p.setPen(group_text_color(group))
            p.setFont(display_font(12, 600))
            p.drawText(mono, Qt.AlignmentFlag.AlignCenter, d["name"][:2].upper())
        left = mono.right() + 12
        right = rect.right() - 12 - STAR_ROOM
        if index.data(ROLE_FAV) is not None:
            paint_star(p, star_rect(option.rect), bool(index.data(ROLE_FAV)), hover)
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
