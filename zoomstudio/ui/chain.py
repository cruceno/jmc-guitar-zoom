"""The signal chain as a row of equal-size pedals with round footswitches, spread over a cable."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QToolButton, QVBoxLayout, QWidget

from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.patches.model import EffectSlot, Patch

from . import strings as S
from . import tokens
from .cards import card_path, with_alpha
from .fonts import display_font, ui_font
from .glass import paint_glow
from .icons import colored, icon
from .mime import MIME_EFFECT, MIME_SLOT
from .theme import group_color, group_fill_color, group_text_color

CHAIN_MIN_TILES = 5  # the chain view always offers at least this many effect positions
PEDAL_W, PEDAL_MIN_W, PEDAL_H = 116, 84, 120
BODY_PAD = 5  # room around the painted pedal for the selection and focus rings
FOOT = 40
JACK_W = 56
GAP = 8


class Footswitch(QAbstractButton):
    """Round on/off switch below a pedal; its accessible name is the action it performs."""

    def __init__(self, effect_name: str = "") -> None:
        super().__init__()
        self.effect_name = effect_name
        self.setCheckable(True)
        self.setFixedSize(FOOT, FOOT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(lambda _on: self.sync_name())

    def sync_name(self) -> None:
        self.setAccessibleName(S.footswitch_name(self.isChecked(), self.effect_name))
        self.setToolTip(self.accessibleName())

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2 + (1 if self.isDown() else 0))
        radius = FOOT / 2 - 4
        face = QRadialGradient(centre - QPointF(radius * 0.3, radius * 0.4), radius * 1.6)
        face.setColorAt(0, tokens.color("footswitch-face").lighter(140))
        face.setColorAt(0.5, tokens.color("footswitch-face"))
        face.setColorAt(1, tokens.color("footswitch-base"))
        p.setBrush(face)
        p.setPen(QPen(tokens.color("border-strong"), 2))
        p.drawEllipse(centre, radius, radius)
        p.setPen(QPen(QColor(0, 0, 0, 115), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centre, radius - 3, radius - 3)
        pix = colored("power", tokens.color("pedal-led-on" if self.isChecked() else "text-primary"), 18)
        p.drawPixmap(int(centre.x() - 9), int(centre.y() - 9), pix)
        if self.hasFocus():
            p.setPen(QPen(tokens.color("focus-ring"), 2))
            p.drawEllipse(centre, radius + 3, radius + 3)


class PedalBody(QFrame):
    """The painted pedal: group band, slot, name, group, badge, LED and state text."""

    def __init__(self, tile: "PedalTile") -> None:
        super().__init__(tile)
        self.tile = tile
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def badge_text(self) -> str:
        return S.BADGE_TWO_SLOTS if self.tile.is_wide else ""

    def legend_text(self) -> str:
        """The line that replaces the group: why the effect cannot be written, or what an empty pedal is for."""
        t = self.tile
        if t.is_empty:
            return S.PEDAL_EMPTY_TARGET if t.selected else S.PEDAL_EMPTY_ADD
        return S.TILE_PROBLEM if t.problem else ""

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        t = self.tile
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(BODY_PAD, BODY_PAD, -BODY_PAD, -BODY_PAD)
        path = card_path(rect)
        base = t.group_colour
        if t.is_empty:
            p.fillPath(path, tokens.color("input-bg"))
            p.setPen(QPen(tokens.color("border-strong"), 1.5, Qt.PenStyle.DashLine))
        else:
            if t.problem:
                fill, border = tokens.color("status-danger-bg"), tokens.color("status-danger")
            elif t.is_enabled_effect:
                fill, border = t.fill_colour, base
            else:
                fill, border = tokens.color("surface-raised"), with_alpha(base, 0.5)
            p.fillPath(path, fill)
            gloss = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gloss.setColorAt(0, tokens.color("pedal-body-top"))
            gloss.setColorAt(0.45, QColor(255, 255, 255, 0))
            p.fillPath(path, gloss)
            p.save()
            p.setClipPath(path)
            band = QRectF(rect.left(), rect.top(), rect.width(), 5)
            p.fillRect(band, tokens.color("status-danger") if t.problem else with_alpha(base, 1.0 if t.is_enabled_effect else 0.4))
            p.restore()
            p.setPen(QPen(border, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        inner = rect.adjusted(10, 9, -10, -8)
        p.setFont(ui_font(12))
        p.setPen(tokens.color("text-secondary"))
        p.drawText(QRectF(inner.left(), inner.top(), inner.width() - 22, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   S.slot_label(t.slot_index, t.is_wide))
        if t.is_empty:
            p.setFont(ui_font(14))
            p.drawText(QRectF(inner.left(), inner.top() + 24, inner.width(), 20), Qt.AlignmentFlag.AlignLeft, S.PEDAL_EMPTY)
            p.setFont(ui_font(12))
            p.drawText(QRectF(inner.left(), inner.bottom() - 34, inner.width(), 36),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap,
                       self.legend_text())
        else:
            p.setFont(display_font(16, 500))
            p.setPen(tokens.color("text-primary" if t.is_enabled_effect else "text-secondary"))
            p.drawText(QRectF(inner.left(), inner.top() + 20, inner.width(), 40),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, t.effect_name)
            p.setFont(ui_font(12))
            if t.problem:  # the group line gives way to why this effect cannot be written to the pedal
                p.setPen(tokens.color("status-danger"))
                p.drawText(QRectF(inner.left(), inner.top() + 50, inner.width(), 32),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                           self.legend_text())
            else:
                p.setPen(t.text_colour)
                p.drawText(QRectF(inner.left(), inner.top() + 50, inner.width(), 16), Qt.AlignmentFlag.AlignLeft,
                           S.group_label(t.group))
            if self.badge_text() and not t.problem:
                badge = QRectF(inner.left(), inner.top() + 67, 52, 15)
                p.setPen(QPen(QColor(255, 255, 255, 46), 1))
                p.drawPath(card_path(badge, 8))
                p.setPen(tokens.color("text-secondary"))
                p.setFont(ui_font(11))
                p.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.badge_text())
            led = QPointF(inner.left() + 5, inner.bottom() - 7)
            if t.is_enabled_effect:
                glow = QRadialGradient(led, 5)
                glow.setColorAt(0, QColor(255, 255, 255))
                glow.setColorAt(1, tokens.color("pedal-led-on"))
                p.setBrush(glow)
                p.setPen(Qt.PenStyle.NoPen)
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(tokens.color("pedal-led-off"), 1.5))
            p.drawEllipse(led, 4.5, 4.5)
            p.setFont(ui_font(12))
            p.setPen(tokens.color("text-secondary"))
            p.drawText(QRectF(led.x() + 11, inner.bottom() - 16, inner.width() - 16, 16), Qt.AlignmentFlag.AlignVCenter,
                       S.POWER_ON if t.is_enabled_effect else S.POWER_OFF)
        if t.selected:
            paint_glow(p, rect, "glow-accent", 12, 4)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(tokens.color("text-primary"), 2))
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 15, 15)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(tokens.color("focus-ring"), 2))
            p.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), 17, 17)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        chain = self.tile.parentWidget()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        if isinstance(chain, ChainView) and key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                chain.step(self.tile, -1 if key == Qt.Key.Key_Left else 1, move=ctrl)
            else:
                chain.go_to(0 if key == Qt.Key.Key_Home else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().focusOutEvent(event)
        self.update()


class PedalTile(QWidget):
    """One effect of the chain (or an empty slot): the pedal body and its footswitch below it.

    ``span`` is the number of chain slots it covers; it never changes the size of the pedal.
    """

    clicked = Signal(int)  # slot index in the patch
    power_toggled = Signal(int, bool)
    remove_requested = Signal(int)
    effect_dropped = Signal(int, int)  # slot index, catalog effect ID
    tile_dropped = Signal(int, int)  # source slot index, target slot index

    def __init__(self, slot_index: int, slot: EffectSlot, info: EffectInfo | None, span: int,
                 problem: str = "") -> None:
        super().__init__()
        self.slot_index = slot_index
        self.problem = problem  # why this effect blocks writing the patch to the pedal ("": none)
        self.span = span
        self.is_empty = slot.is_empty
        self.is_wide = span == 2
        self.group = info.group if info else ""
        self.is_enabled_effect = slot.enabled and not slot.is_empty
        self.selected = False
        self.effect_name = "" if slot.is_empty else (info.name if info else f"0x{slot.effect_id:08X}")
        known = bool(info)
        self.group_colour = group_color(self.group) if known else tokens.color("border-strong")
        self.fill_colour = group_fill_color(self.group) if known else tokens.color("surface-raised")
        self.text_colour = group_text_color(self.group) if known else tokens.color("text-secondary")
        self._press_pos = None
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.body = PedalBody(self)
        self.body.setFixedHeight(PEDAL_H + 2 * BODY_PAD)
        self.power = Footswitch(self.effect_name)
        self.power.setChecked(slot.enabled)
        self.power.sync_name()
        self.power.setVisible(not slot.is_empty)
        sp = self.power.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.power.setSizePolicy(sp)
        self.power.toggled.connect(self._on_power)
        layout.addWidget(self.body)
        layout.addWidget(self.power, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.remove_button = QToolButton(self)
        self.remove_button.setObjectName("removeButton")
        self.remove_button.setIcon(icon("close", size=14))
        self.remove_button.setToolTip(S.REMOVE_EFFECT)
        self.remove_button.setAccessibleName(f"{S.REMOVE} {self.effect_name}")
        self.remove_button.setFixedSize(22, 22)
        self.remove_button.setVisible(not slot.is_empty)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.slot_index))
        self.set_pedal_width(PEDAL_W)
        if slot.is_empty:
            self.setToolTip(S.SLOT_EMPTY_TIP)
        elif info:
            self.setToolTip(S.tile_tip(info.name, S.group_label(info.group), info.dsp_load_percent, self.is_wide))
        if problem:
            self.setToolTip(S.tile_problem_tip(problem) + self.toolTip())
        self.body.setAccessibleName(f"{S.slot_label(slot_index, self.is_wide)}: {self.effect_name or S.PEDAL_EMPTY}")
        self.body.setAccessibleDescription(
            "" if slot.is_empty else f"{S.group_label(self.group)}, {S.POWER_ON if self.is_enabled_effect else S.POWER_OFF}")

    def set_pedal_width(self, width: int) -> None:
        self.setFixedSize(width, PEDAL_H + 2 * BODY_PAD + 2 + FOOT)
        self.remove_button.move(width - BODY_PAD - 28, BODY_PAD + 8)

    def _on_power(self, on: bool) -> None:
        self.is_enabled_effect = on
        self.body.setAccessibleDescription(f"{S.group_label(self.group)}, {S.POWER_ON if on else S.POWER_OFF}")
        self.body.update()
        self.power_toggled.emit(self.slot_index, on)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.body.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        if self.is_empty:  # a dashed circle where the footswitch would be
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(with_alpha(tokens.color("border-strong"), 0.6), 1.5, Qt.PenStyle.DashLine))
            c = self.power.geometry().center()
            p.drawEllipse(QPointF(c.x(), c.y()), FOOT / 2 - 4, FOOT / 2 - 4)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._press_pos = event.position().toPoint()
        self.body.setFocus()
        self.clicked.emit(self.slot_index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if (self.is_empty or self._press_pos is None or not event.buttons() & Qt.MouseButton.LeftButton
                or (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance()):
            return super().mouseMoveEvent(event)
        mime = QMimeData()
        mime.setData(MIME_SLOT, QByteArray(str(self.slot_index).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.body.grab())
        self._press_pos = None
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        mime = event.mimeData()
        if mime.hasFormat(MIME_EFFECT) or mime.hasFormat(MIME_SLOT):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt API)
        mime = event.mimeData()
        if mime.hasFormat(MIME_EFFECT):
            self.effect_dropped.emit(self.slot_index, int(bytes(mime.data(MIME_EFFECT)).decode()))
        elif mime.hasFormat(MIME_SLOT):
            self.tile_dropped.emit(int(bytes(mime.data(MIME_SLOT)).decode()), self.slot_index)
        else:
            return
        event.acceptProposedAction()


EffectTile = PedalTile  # the name the rest of the UI and the tests know


class ChainView(QWidget):
    """Signal chain of the selected patch: Entrada, equal-size pedals evenly spread over a cable, Salida."""

    tile_selected = Signal(int)
    power_toggled = Signal(int, bool)
    remove_requested = Signal(int)
    effect_dropped = Signal(int, int)
    tile_moved = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._tiles: list[PedalTile] = []
        self._selected: int | None = None
        self._restore_focus = False
        self.setFixedHeight(PEDAL_H + 2 * BODY_PAD + 2 + FOOT + 12)

    def tiles(self) -> list[PedalTile]:
        return list(self._tiles)

    def clear(self) -> None:
        self._restore_focus = any(t.body.hasFocus() for t in self._tiles)  # the rebuild must not drop the focus
        for tile in self._tiles:
            tile.setParent(None)  # leave the window now; deleteLater alone keeps painting it
            tile.deleteLater()
        self._tiles = []
        self._selected = None

    def set_patch(self, patch: Patch | None, catalog: dict[int, EffectInfo],
                  problems: dict[int, str] | None = None) -> None:
        self.clear()
        if patch is None:
            self.update()
            return
        slots = patch.effects
        for i, slot in enumerate(slots):
            if slot.is_wide_filler:
                continue  # covered by the "2 slots" pedal before it
            info = catalog.get(slot.effect_id)
            followed_by_filler = i + 1 < len(slots) and slots[i + 1].is_wide_filler
            wide = not slot.is_empty and (followed_by_filler or (info is not None and info.is_wide))
            self._add_tile(PedalTile(i, slot, info, 2 if wide else 1, (problems or {}).get(i, "")))
        for k in range(max(0, CHAIN_MIN_TILES - len(self._tiles))):
            # empty drop targets beyond the stored chain (slot indexes past the end of the patch)
            self._add_tile(PedalTile(len(slots) + k, EffectSlot(), None, 1))
        self.updateGeometry()
        self._arrange()

    def _add_tile(self, tile: PedalTile) -> None:
        tile.setParent(self)
        tile.clicked.connect(self.select)
        tile.power_toggled.connect(self.power_toggled)
        tile.remove_requested.connect(self.remove_requested)
        tile.effect_dropped.connect(self.effect_dropped)
        tile.tile_dropped.connect(self.tile_moved)
        tile.show()
        self._tiles.append(tile)

    def pedal_width(self) -> int:
        n = max(CHAIN_MIN_TILES, len(self._tiles))
        free = self.width() - 2 * JACK_W
        return max(PEDAL_MIN_W, min(PEDAL_W, (free - GAP * (n + 1)) // n))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        n = max(CHAIN_MIN_TILES, len(self._tiles))
        return QSize(2 * JACK_W + n * PEDAL_MIN_W + (n + 1) * GAP, self.height())

    def _arrange(self) -> None:
        n = len(self._tiles)
        if not n:
            return
        w = self.pedal_width()
        free = self.width() - 2 * JACK_W
        gap = max(GAP, (free - n * w) / (n + 1))
        for i, tile in enumerate(self._tiles):
            tile.set_pedal_width(w)
            tile.move(round(JACK_W + gap + i * (w + gap)), 4)
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._arrange()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = 4 + BODY_PAD + PEDAL_H / 2
        x0, x1 = JACK_W / 2, self.width() - JACK_W / 2
        p.setPen(QPen(tokens.color("cable"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
        p.setFont(ui_font(12))
        for x, label in ((x0, S.JACK_IN), (x1, S.JACK_OUT)):
            glow = QRadialGradient(QPointF(x, y), 9)
            glow.setColorAt(0, tokens.color("footswitch-face").lighter(150))
            glow.setColorAt(1, tokens.color("footswitch-base"))
            p.setBrush(glow)
            p.setPen(QPen(tokens.color("border-strong"), 1.5))
            p.drawEllipse(QPointF(x, y), 8, 8)
            p.setPen(tokens.color("text-secondary"))
            p.drawText(QRectF(x - JACK_W / 2, y + 14, JACK_W, 18), Qt.AlignmentFlag.AlignCenter, label)

    def step(self, tile: PedalTile, delta: int, move: bool = False) -> None:
        """Select the neighbouring pedal, or (``move``) move this effect onto its place."""
        i = self._tiles.index(tile) + delta
        if not 0 <= i < len(self._tiles):
            return
        if not move:
            self.go_to(i)
        elif not tile.is_empty and not self._tiles[i].is_empty:
            self._restore_focus = True
            self.tile_moved.emit(tile.slot_index, self._tiles[i].slot_index)

    def go_to(self, index: int) -> None:
        """Select the pedal at ``index`` (-1: the last) and give it the keyboard focus."""
        if self._tiles:
            tile = self._tiles[index]
            self.select(tile.slot_index)
            tile.body.setFocus()

    def select(self, slot_index: int | None) -> None:
        self._selected = slot_index
        for tile in self._tiles:
            chosen = tile.slot_index == slot_index
            tile.set_selected(chosen)
            tile.body.setFocusPolicy(Qt.FocusPolicy.StrongFocus if chosen or slot_index is None
                                     else Qt.FocusPolicy.ClickFocus)  # one tab stop: the selected pedal
            if chosen and self._restore_focus:
                tile.body.setFocus()
                self._restore_focus = False
        if slot_index is not None:
            self.tile_selected.emit(slot_index)

    @property
    def selected_slot(self) -> int | None:
        return self._selected
