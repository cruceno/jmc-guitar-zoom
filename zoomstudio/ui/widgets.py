"""Building blocks of the main window: chain tiles, parameter knobs, effect catalog."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDial, QFrame, QGridLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QProgressBar, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.effects.i18n import effect_description, param_explanation
from zoomstudio.patches.model import EffectSlot, Patch

from . import strings as S
from . import tokens
from .cards import ROLE_EFFECT, ROLE_FAV, ROLE_SECTION, FAVORITES_KEY, SectionList, set_section_header, EffectCardDelegate, Knob, PatchCardDelegate, card_path, pedal_thumbnail, svg_thumbnail, with_alpha
from .favorites import FavoritesStore
from .fonts import display_font, ui_font
from .icons import icon, pixmap
from .painted import GroupChip, SectionLabel
from .chain import CHAIN_MIN_TILES, ChainView, EffectTile, PedalTile  # noqa: F401  (re-exported)
from .mime import MIME_EFFECT, MIME_PATCH, MIME_SLOT  # noqa: F401  (re-exported)
from .theme import group_color

ALL_GROUPS = S.ALL_GROUPS
FAVORITES_FILTER = "\0favorites"  # the group combo's «Favoritos» option (no group has this key)
_ID_ROLE = Qt.ItemDataRole.UserRole
_NAME_ROLE = Qt.ItemDataRole.UserRole + 1
PREVIEW_W, PREVIEW_H = 52, 74  # the preview of the detail card (the prototype's pedal thumbnail)
DETAIL_TEXT_H = 84  # description area of the catalog detail card: 5 lines, scrolls beyond that


class PatchList(QListWidget):
    """Patch list whose rows can be dragged onto each other (a swap request, never a move)."""

    patch_dropped = Signal(int, int)  # source location, target location

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.IgnoreAction)
        self.setItemDelegate(PatchCardDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)

    def mimeData(self, items) -> QMimeData:  # noqa: N802 (Qt API)
        mime = QMimeData()
        if items:
            mime.setData(MIME_PATCH, QByteArray(str(items[0].data(Qt.ItemDataRole.UserRole)).encode()))
        return mime

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasFormat(MIME_PATCH):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasFormat(MIME_PATCH) and self.itemAt(event.position().toPoint()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt API)
        item = self.itemAt(event.position().toPoint())
        if not event.mimeData().hasFormat(MIME_PATCH) or item is None:
            event.ignore()
            return
        source = int(bytes(event.mimeData().data(MIME_PATCH)).decode())
        event.acceptProposedAction()
        self.patch_dropped.emit(source, int(item.data(Qt.ItemDataRole.UserRole)))


class ParamRow(QWidget):
    """Parameter card: name, knob, value box and range. Dial and spin stay in sync."""

    changed = Signal(int, int)  # parameter index, new value
    activated = Signal(int)  # the card got the focus or was edited: its help is shown

    def __init__(self, index: int, name: str, maximum: int, default: int, value: int, tooltip: str = "") -> None:
        super().__init__()
        self.index = index
        self.name = name
        self.default = default
        self.explanation = tooltip
        self.current = False
        maximum = max(maximum, value)  # never hide a stored value that exceeds the catalog range
        self.maximum = maximum
        self.dial = Knob()
        self.dial.setRange(0, maximum)
        self.dial.default_value = default
        self.spin = QSpinBox()
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setRange(0, maximum)
        self.dial.setValue(value)
        self.spin.setValue(value)
        self.label = QLabel(name)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFont(ui_font(14, QFont.Weight.Medium))
        self.range_label = QLabel(S.param_range(maximum, default))
        self.range_label.setProperty("role", "secondary")
        self.range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.range_label.setWordWrap(True)  # «0–100 · pred. 40» wraps in a narrow card, as in the prototype
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(3)
        layout.addWidget(self.label)
        layout.addWidget(self.dial, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.spin)
        layout.addWidget(self.range_label)
        if tooltip:
            self.setToolTip(tooltip)
        self.dial.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.dial.setValue)
        self.spin.valueChanged.connect(lambda v: self.changed.emit(self.index, v))
        self.spin.valueChanged.connect(lambda _v: self.activated.emit(self.index))
        self.dial.mouseDoubleClickEvent = lambda _e: self.spin.setValue(self.default)  # type: ignore[method-assign]
        for w in (self.dial, self.spin):
            w.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.FocusIn:
            self.activated.emit(self.index)
        return super().eventFilter(obj, event)

    def reset(self) -> None:
        self.spin.setValue(self.default)

    def set_current(self, current: bool) -> None:
        self.current = current
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = card_path(rect)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if self.current:
            fill.setColorAt(0, with_alpha(tokens.color("card-selected"), 0.28))
            fill.setColorAt(1, with_alpha(tokens.color("card-selected"), 0.12))
        else:
            fill.setColorAt(0, tokens.color("card-top"))
            fill.setColorAt(1, tokens.color("card-bottom"))
        p.fillPath(path, fill)
        p.setPen(QPen(with_alpha(tokens.color("accent"), 0.55) if self.current else tokens.color("card-rim"), 1))
        p.drawPath(path)


class DetailCard(QFrame):
    """Card with two columns split by a hairline: the selected parameter | the selected effect."""

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = card_path(rect)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0, tokens.color("card-top"))
        fill.setColorAt(1, tokens.color("card-bottom"))
        p.fillPath(path, fill)
        p.setPen(QPen(tokens.color("card-rim"), 1))
        p.drawPath(path)
        layout = self.layout()
        divider = layout.itemAt(0).geometry().right() + layout.spacing() // 2 if layout and layout.count() > 1 else 0
        if divider:
            p.setPen(QPen(tokens.color("hairline"), 1))
            p.drawLine(divider, int(rect.top() + 14), divider, int(rect.bottom() - 14))


class ParamPanel(QWidget):
    """Parameter cards of the selected effect and, below them, the detail card (parameter | effect)."""

    param_changed = Signal(int, int)  # parameter index, value

    COLUMNS = 7

    def __init__(self, installed_label: str = "") -> None:
        super().__init__()
        self.installed_label = installed_label
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        self.title = QLabel(S.SELECT_EFFECT)
        self.title.setProperty("role", "heading")
        self.chip = GroupChip()
        self.chip.hide()
        self.slot_caption = QLabel("")
        self.slot_caption.setProperty("role", "secondary")
        self.off_caption = QLabel(S.POWER_OFF)
        self.off_caption.setProperty("role", "off")
        self.off_caption.hide()
        self.hint = QLabel("")
        self.hint.setProperty("role", "secondary")
        head = QHBoxLayout()
        head.setSpacing(10)
        for w in (self.title, self.chip, self.slot_caption, self.off_caption):
            head.addWidget(w, alignment=Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        head.addWidget(self.hint, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        # empty slot: instructions instead of knobs
        self.empty_title = QLabel("")
        self.empty_title.setProperty("role", "strong")
        self.empty_text = QLabel("")
        self.empty_text.setWordWrap(True)
        self.empty_text.setProperty("role", "hint")
        self._empty = QWidget()
        empty_lay = QVBoxLayout(self._empty)
        empty_lay.addWidget(self.empty_title)
        empty_lay.addWidget(self.empty_text)
        empty_lay.addStretch(1)
        self._empty.hide()
        # detail card
        self.param_icon = QLabel()
        self.param_icon.setPixmap(pixmap("info", tokens.color("text-secondary").name(), 16))
        self.param_name = QLabel("")
        self.param_name.setProperty("role", "strong")
        self.help = QLabel("")  # the parameter help: Spanish texts run long, so it wraps and scrolls
        self.help.setWordWrap(True)
        self.help.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.help.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.help_scroll = _wrapping_scroll(self.help)
        self.param_facts = QLabel("")
        self.param_facts.setProperty("role", "secondary")
        self.param_facts.setWordWrap(True)
        self.reset_button = QPushButton(S.RESET)
        self.reset_button.setIcon(icon("reset"))
        self.reset_button.setEnabled(False)
        self.reset_button.clicked.connect(self._reset_current)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_row.addWidget(self.param_icon)
        name_row.addWidget(self.param_name, stretch=1)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addLayout(name_row)
        left.addWidget(self.help_scroll, stretch=1)
        left.addWidget(self.param_facts)
        left.addWidget(self.reset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.effect_name = QLabel("")
        self.effect_name.setProperty("role", "strong")
        self.description = QLabel("")  # the effect description: long, so it wraps and scrolls instead of clipping
        self.description.setWordWrap(True)
        self.description.setProperty("role", "desc")
        self.description.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.description_scroll = _wrapping_scroll(self.description)
        self.effect_facts = QLabel("")
        self.effect_facts.setProperty("role", "secondary")
        self.effect_facts.setWordWrap(True)
        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(self.effect_name)
        right.addWidget(self.description_scroll, stretch=1)
        right.addWidget(self.effect_facts)
        self.card = DetailCard()
        card_lay = QHBoxLayout(self.card)
        card_lay.setContentsMargins(16, 12, 16, 12)
        card_lay.setSpacing(28)
        card_lay.addLayout(left, stretch=1)  # equal columns, as in the prototype
        card_lay.addLayout(right, stretch=1)
        outer.addLayout(head)
        outer.addWidget(self._grid_host)
        outer.addWidget(self._empty)
        outer.addWidget(self.card, stretch=1)
        outer.addStretch(0)
        self._rows: list[ParamRow] = []
        self._current: ParamRow | None = None
        self.clear()

    def rows(self) -> list[ParamRow]:
        return list(self._rows)

    def _reset_view(self) -> None:
        for row in self._rows:
            self._grid.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        self._current = None
        for w in (self.chip, self.off_caption):
            w.hide()
        for label in (self.slot_caption, self.hint, self.param_name, self.help, self.param_facts,
                      self.effect_name, self.description, self.effect_facts):
            label.setText("")
        self.reset_button.setEnabled(False)
        self.reset_button.setVisible(True)
        self.param_icon.hide()
        self._empty.hide()
        self._grid_host.show()
        self.card.show()

    def clear(self, message: str = S.SELECT_EFFECT) -> None:
        self._reset_view()
        self.title.setText(message)
        self.card.hide()

    def show_empty(self, slot_index: int) -> None:
        """An empty pedal is selected: say what it takes to fill it (no knobs, no detail card)."""
        self._reset_view()
        self._grid_host.hide()
        self.card.hide()
        self.empty_title.setText(S.empty_slot_title(slot_index + 1))
        self.empty_text.setText(S.empty_slot_instructions(slot_index + 1))
        self._empty.show()
        self.title.setText("")  # the panel states the case itself

    def show_effect(self, slot: EffectSlot, info: EffectInfo | None, slot_label: str = "") -> None:
        self._reset_view()
        if info is None:
            self.title.setText(S.unknown_effect_title(slot.effect_id))
            self.card.hide()
            return
        self.title.setText(info.name)
        self.chip.set_group(S.group_label(info.group), info.group)
        self.chip.show()
        self.slot_caption.setText(slot_label)
        self.off_caption.setVisible(not slot.enabled)
        self.hint.setText(S.PARAM_HINT)
        self.effect_name.setText(info.name)
        self.description.setText(effect_description(info))
        installed = bool(self.installed_label) and self.installed_label in info.sources
        self.effect_facts.setText(S.effect_facts(info.dsp_load_percent, info.is_wide, installed))
        self.param_icon.show()
        for i, param in enumerate(info.params[: len(slot.params)]):
            row = ParamRow(i, param.name, param.max, param.default, slot.params[i], param_explanation(param))
            row.changed.connect(self.param_changed)
            row.changed.connect(lambda _i, _v, r=row: self._refresh_param(r))
            row.activated.connect(lambda _idx, r=row: self._select(r) if r in self._rows else None)
            self._grid.addWidget(row, i // self.COLUMNS, i % self.COLUMNS)
            self._rows.append(row)
        if self._rows:
            self._select(self._rows[0])

    def _select(self, row: ParamRow) -> None:
        if self._current is not None:
            self._current.set_current(False)
        self._current = row
        row.set_current(True)
        self.param_name.setText(row.name)
        self.help.setText(row.explanation or S.NO_PARAM_HELP)
        self._refresh_param(row)

    def _refresh_param(self, row: ParamRow) -> None:
        if row is not self._current:
            return
        value = row.spin.value()
        self.param_facts.setText(S.param_facts(value, row.maximum, row.default))
        self.reset_button.setEnabled(value != row.default)

    def _reset_current(self) -> None:
        if self._current is not None:
            self._current.reset()


class _CatalogList(SectionList):
    """Catalog rows that can be dragged onto a chain tile (payload: the effect ID); Enter activates a row."""

    enter_pressed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setItemDelegate(EffectCardDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentItem() is not None
                and not self.is_header(self.currentItem())):  # on a header Enter folds it (SectionList)
            self.enter_pressed.emit(self.currentItem())
            event.accept()
            return
        super().keyPressEvent(event)

    def mimeData(self, items) -> QMimeData:  # noqa: N802 (Qt API)
        mime = QMimeData()
        if items and not self.is_header(items[0]):
            mime.setData(MIME_EFFECT, QByteArray(str(items[0].data(_ID_ROLE)).encode()))
        return mime


class DestinationCard(QFrame):
    """Where the selected effect would go: a sentence and a minimap of the chain with the target outlined."""

    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.strip: list[tuple[str | None, int, bool]] = []
        self.setFixedHeight(64)

    def set_destination(self, text: str, strip: list[tuple[str | None, int, bool]]) -> None:
        self.text, self.strip = text, strip
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = card_path(rect)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0, tokens.color("card-top"))
        fill.setColorAt(1, tokens.color("card-bottom"))
        p.fillPath(path, fill)
        p.setPen(QPen(tokens.color("card-rim"), 1))
        p.drawPath(path)
        p.drawPixmap(int(rect.left() + 12), int(rect.top() + 9), pixmap("target", tokens.color("text-secondary").name(), 16))
        p.setFont(ui_font(14, QFont.Weight.Medium))
        p.setPen(tokens.color("text-primary"))
        p.drawText(QRectF(rect.left() + 34, rect.top() + 6, rect.width() - 44, 22), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(ui_font(14, QFont.Weight.Medium)).elidedText(
                       self.text, Qt.TextElideMode.ElideRight, int(rect.width() - 44)))
        total = sum(span for _g, span, _t in self.strip) or 1
        gap, left, width = 4, rect.left() + 12, rect.width() - 24
        unit = (width - gap * (len(self.strip) - 1)) / total
        x = left
        for group, span, target in self.strip:
            seg = QRectF(x, rect.bottom() - 22, unit * span, 10)
            if group is None:
                p.setPen(QPen(tokens.color("border-strong"), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(group_color(group))
            p.drawRoundedRect(seg, 5, 5)
            if target:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(tokens.color("text-primary"), 2))
                p.drawRoundedRect(seg.adjusted(-2, -2, 2, 2), 6, 6)
            x += seg.width() + gap


class CatalogPanel(QWidget):
    """Searchable effect catalog: filters, effect cards, the destination of the selected effect and its detail."""

    effect_activated = Signal(int)  # double click on a row: catalog effect ID
    manage_requested = Signal()  # the «Administrar» button: open the pedal's effects screen

    def __init__(self, catalog: dict[int, EffectInfo], a1_ids: set[int] | None, installed_label: str,
                 favorites: FavoritesStore | None = None) -> None:
        super().__init__()
        self.favorites = favorites if favorites is not None else FavoritesStore()
        self._catalog = catalog
        self._a1_ids = a1_ids
        self._installed_label = installed_label
        self._current_dsp = 0.0
        self._replaced_dsp = 0.0
        self._opened: set[str] = set()  # sections the user unfolded (kept for the session)
        self._closed: set[str] = set()  # sections the user folded
        self._searching_folded: set[str] = set()  # folded by hand while a search or a group choice shows them all
        self._selected_group: str | None = None  # group of the effect selected in the chain: starts open
        self._target_enabled = False
        self._has_svg = False
        self.search = QLineEdit()
        self.search.setPlaceholderText(S.SEARCH_EFFECTS)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(S.SEARCH_EFFECTS_TIP)
        self.search.addAction(icon("search", "text-secondary", 17), QLineEdit.ActionPosition.LeadingPosition)
        self.group_combo = QComboBox()
        self.group_combo.addItem(ALL_GROUPS)
        self.group_combo.addItem(S.FAVORITES, FAVORITES_FILTER)
        for group in sorted({e.group for e in catalog.values()}):
            self.group_combo.addItem(S.group_label(group), group)
        self.a1_check = QCheckBox(S.ONLY_A1)
        self.a1_check.setEnabled(a1_ids is not None)
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "secondary")
        self.destination = DestinationCard()
        self.list = _CatalogList()
        # nothing matches: say so and offer the way back instead of an empty list
        self.none_label = QLabel("")
        self.none_label.setWordWrap(True)
        self.clear_button = QPushButton(S.CLEAR_SEARCH)
        self.clear_button.clicked.connect(self.clear_filters)
        self.none_box = QWidget()
        none_lay = QVBoxLayout(self.none_box)
        none_lay.addWidget(self.none_label)
        none_lay.addWidget(self.clear_button, alignment=Qt.AlignmentFlag.AlignLeft)
        none_lay.addStretch(1)
        self.none_box.hide()
        # detail card
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_name = QLabel("")
        self.detail_name.setProperty("role", "strong")
        self.detail_facts = QLabel("")
        self.detail_facts.setProperty("role", "secondary")
        self.detail = QLabel("")  # the effect description: wraps and scrolls instead of taking the list's room
        self.detail.setWordWrap(True)
        self.detail.setProperty("role", "desc")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidget(self.detail)
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_scroll.setFixedHeight(DETAIL_TEXT_H)
        self.detail_scroll.viewport().setAutoFillBackground(False)
        self.after_bar = QProgressBar()
        self.after_bar.setRange(0, 100)
        self.after_bar.setTextVisible(False)
        self.after_bar.setFixedWidth(72)
        self.after_value = QLabel("")
        self.after_value.setProperty("role", "value")
        self.after_row = QWidget()
        after_lay = QHBoxLayout(self.after_row)
        after_lay.setContentsMargins(0, 0, 0, 0)
        after_lay.setSpacing(8)
        after_label = QLabel(S.DSP_AFTER)
        after_label.setProperty("role", "secondary")
        for w in (after_label, self.after_bar, self.after_value):
            after_lay.addWidget(w)
        after_lay.addStretch(1)
        self.target_button = QPushButton(S.NO_TARGET)
        self.target_button.setEnabled(False)
        self.target_button.clicked.connect(self._activate_current)
        self.hint = QLabel(S.ENTER_HINT)
        self.hint.setProperty("role", "secondary")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QHBoxLayout()
        title.addWidget(self.detail_name, stretch=1)
        title.addWidget(self.detail_facts)
        text.addLayout(title)
        text.addWidget(self.detail_scroll)
        text.addWidget(self.after_row)
        top.addLayout(text, stretch=1)
        self.detail_card = DetailCard()
        card = QVBoxLayout(self.detail_card)
        card.setContentsMargins(12, 12, 12, 10)
        card.setSpacing(8)
        card.addLayout(top)
        card.addWidget(self.target_button)
        card.addWidget(self.hint)
        filters = QHBoxLayout()
        filters.setSpacing(10)
        filters.addWidget(self.group_combo, stretch=1)
        filters.addWidget(self.a1_check)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(self._header())
        found = QHBoxLayout()  # the search field and how many effects it leaves (the header is the title and «Administrar»)
        found.setSpacing(10)
        found.addWidget(self.search, stretch=1)
        found.addWidget(self.count_label)
        layout.addLayout(found)
        layout.addLayout(filters)
        layout.addWidget(self.destination)
        layout.addWidget(self.list, stretch=1)
        layout.addWidget(self.none_box, stretch=1)
        layout.addWidget(self.detail_card)
        self._chain_ids: set[int] = set()
        self.search.textChanged.connect(self.refresh)
        self.group_combo.currentIndexChanged.connect(self.refresh)
        self.a1_check.toggled.connect(self.refresh)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemDoubleClicked.connect(
            lambda item: None if item.data(ROLE_SECTION) else self.effect_activated.emit(item.data(_ID_ROLE)))
        self.list.enter_pressed.connect(lambda item: self.effect_activated.emit(item.data(_ID_ROLE)))
        self.list.favorite_toggled.connect(lambda item: self.favorites.toggle(item.data(_ID_ROLE)))
        self.list.section_toggled.connect(self._on_section_toggled)
        self.favorites.changed.connect(self._on_favorites_changed)
        self.refresh()

    def _on_favorites_changed(self) -> None:
        self.refresh(keep=True)  # favourites live in their own section

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(SectionLabel(S.CATALOG_TITLE))
        row.addStretch(1)
        self.manage_button = QPushButton(S.CATALOG_MANAGE)
        self.manage_button.setIcon(icon("package"))
        self.manage_button.setToolTip(S.EFFECTS_TIP)
        self.manage_button.setAccessibleName(S.EFFECTS_TIP)
        self.manage_button.clicked.connect(self.manage_requested)
        row.addWidget(self.manage_button)
        return row

    def _is_installed(self, info: EffectInfo) -> bool:
        return self._installed_label in info.sources

    def _matches(self, info: EffectInfo) -> bool:
        text = self.search.text().strip().lower()
        if text and text not in info.name.lower() and text not in info.group.lower():
            return False
        group = self.group_combo.currentData()
        if group == FAVORITES_FILTER:
            if not self.favorites.is_favorite(info.effect_id):
                return False
        elif group is not None and info.group != group:
            return False
        return not (self.a1_check.isChecked() and self._a1_ids is not None
                    and info.effect_id not in self._a1_ids)

    def clear_filters(self) -> None:
        """Back to the whole catalog: empty search and every group (the A1 FOUR filter stays as chosen)."""
        self.search.clear()
        self.group_combo.setCurrentIndex(0)

    # -- sections

    def _filtering(self) -> bool:
        """A search or a chosen group shows every matching section unfolded."""
        return bool(self.search.text().strip()) or self.group_combo.currentData() is not None

    def _expanded(self, key: str) -> bool:
        if self._filtering():
            return key not in self._searching_folded
        if key in self._opened:
            return True
        if key in self._closed:
            return False
        return key == FAVORITES_KEY or key == self._selected_group

    def _on_section_toggled(self, header: QListWidgetItem) -> None:
        key, _count, expanded = header.data(ROLE_SECTION)
        if self._filtering():
            self._searching_folded.discard(key) if not expanded else self._searching_folded.add(key)
        elif expanded:
            self._opened.discard(key)
            self._closed.add(key)
        else:
            self._closed.discard(key)
            self._opened.add(key)
        self.list.set_section_expanded(header, not expanded)

    def set_selected_group(self, group: str | None) -> None:
        """The effect selected in the chain: its section opens unless the user folded it before."""
        if group == self._selected_group:
            return
        self._selected_group = group
        if group is not None and not self._filtering():
            for i in range(self.list.count()):
                header = self.list.item(i)
                if header.data(ROLE_SECTION) and header.data(ROLE_SECTION)[0] == group:
                    self.list.set_section_expanded(header, self._expanded(group))

    def section_groups(self) -> list[str]:
        return [h.data(ROLE_SECTION)[0] for h in self._section_items()]

    def section_count(self, group: str) -> int:
        return self._section_item(group).data(ROLE_SECTION)[1]

    def section_expanded(self, group: str) -> bool:
        return self._section_item(group).data(ROLE_SECTION)[2]

    def section_header_row(self, group: str) -> int:
        return self.list.row(self._section_item(group))

    def toggle_section(self, group: str) -> None:
        self._on_section_toggled(self._section_item(group))

    def _section_items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(ROLE_SECTION)]

    def _section_item(self, group: str) -> QListWidgetItem:
        return next(h for h in self._section_items() if h.data(ROLE_SECTION)[0] == group)

    def item_of(self, name: str) -> QListWidgetItem:
        """The row of the effect called ``name`` (it may be hidden inside a folded section)."""
        return next(self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(_NAME_ROLE) == name)

    def row_of(self, name: str) -> int:
        return self.list.row(self.item_of(name))

    def _effect_items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count()) if not self.list.item(i).data(ROLE_SECTION)]

    def _current_effect(self) -> QListWidgetItem | None:
        item = self.list.currentItem()
        return None if item is None or item.data(ROLE_SECTION) else item

    def refresh(self, keep: bool = False) -> None:
        """Rebuild the sections. ``keep``: leave the selected effect selected when it is still listed."""
        current = self._current_effect()
        kept_id = current.data(_ID_ROLE) if keep and current is not None else None
        self._searching_folded = self._searching_folded if self._filtering() else set()
        self.list.blockSignals(True)
        self.list.clear()
        shown = [info for info in sorted(self._catalog.values(), key=lambda e: (e.group, e.name.lower()))
                 if self._matches(info)]

        def section_of(info: EffectInfo) -> str:
            return FAVORITES_KEY if self.favorites.is_favorite(info.effect_id) else info.group

        restore = None
        for key in sorted({section_of(i) for i in shown}, key=lambda k: (k != FAVORITES_KEY, k)):
            members = [i for i in shown if section_of(i) == key]
            expanded = self._expanded(key)
            header = QListWidgetItem()
            set_section_header(header, key, len(members), expanded)
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.list.addItem(header)
            for info in members:
                item = QListWidgetItem(S.catalog_row(info.name, info.group, info.dsp_load_percent,
                                                     self._is_installed(info)))
                item.setData(ROLE_EFFECT, {
                    "name": info.name, "group": info.group, "dsp": info.dsp_load_percent, "wide": info.is_wide,
                    "installed": self._is_installed(info), "in_chain": info.effect_id in self._chain_ids,
                    "svg": info.svg_path,
                    "blocked": self._a1_ids is not None and info.effect_id not in self._a1_ids})
                item.setData(_ID_ROLE, info.effect_id)
                item.setData(ROLE_FAV, self.favorites.is_favorite(info.effect_id))
                item.setData(_NAME_ROLE, info.name)
                item.setForeground(group_color(info.group).lighter(150))
                self.list.addItem(item)
                item.setHidden(not expanded)  # only once it belongs to the list
                if info.effect_id == kept_id:
                    restore = item
        self.list.blockSignals(False)
        if restore is not None:
            self.list.setCurrentItem(restore)
        count = len(shown)
        self.count_label.setText(S.visible_count(count))
        self.list.setVisible(count > 0)
        self.none_box.setVisible(count == 0)
        if count == 0:
            group = self.group_combo.currentData()
            self.none_label.setText(S.no_effect_matches(
                self.search.text().strip(), (S.FAVORITES if group == FAVORITES_FILTER else S.group_label(group)) if group else "",
                self.a1_check.isChecked() and self._a1_ids is not None))
            self._on_current(None)
        elif restore is None:
            self._on_current(None)  # the list was rebuilt: nothing is selected until a card is

    def set_target(self, text: str, enabled: bool) -> None:
        """What the button does to the selected pedal ("Agregar al slot 3"); disabled without a patch."""
        self.target_button.setText(text)
        self.target_button.setEnabled(enabled and self._current_effect() is not None)
        self._target_enabled = enabled

    def set_destination(self, text: str, strip: list[tuple[str | None, int, bool]], dsp: float,
                        replaced_dsp: float) -> None:
        """The destination card (sentence + minimap) and the numbers behind «DSP después»."""
        self.destination.set_destination(text, strip)
        self.destination.setVisible(bool(strip))
        self._current_dsp, self._replaced_dsp = dsp, replaced_dsp
        self._show_after(self._current_effect())

    def set_chain_effects(self, ids: set[int]) -> None:
        self._chain_ids = set(ids)
        for item in self._effect_items():
            data = dict(item.data(ROLE_EFFECT))
            data["in_chain"] = item.data(_ID_ROLE) in self._chain_ids
            item.setData(ROLE_EFFECT, data)
        self.list.viewport().update()

    def _activate_current(self) -> None:
        item = self._current_effect()
        if item is not None:
            self.effect_activated.emit(item.data(_ID_ROLE))

    def visible_names(self) -> list[str]:
        return [item.data(_NAME_ROLE) for item in self._effect_items()]

    def _show_after(self, item: QListWidgetItem | None) -> None:
        """«DSP después»: the load of the patch once the selected effect replaces (or fills) the target."""
        show = item is not None and self._target_enabled
        self.after_row.setVisible(show)
        if not show:
            return
        info = self._catalog[item.data(_ID_ROLE)]
        after = self._current_dsp - self._replaced_dsp + info.dsp_load_percent
        over = after > 100
        self.after_bar.setValue(min(100, round(after)))
        self.after_value.setText(S.dsp_value(after))
        for widget in (self.after_bar, self.after_value):
            widget.setProperty("over", over)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _on_current(self, item: QListWidgetItem | None, _prev=None) -> None:
        if item is not None and item.data(ROLE_SECTION):
            item = None  # a section header has no effect to describe or add
        self.preview.clear()
        self._has_svg = False
        self.detail.setText("")
        self.detail_name.setText("")
        self.detail_facts.setText("")
        self.target_button.setEnabled(item is not None and self._target_enabled)
        self.detail_card.setVisible(item is not None)
        self._show_after(item)
        if item is None:
            return
        info = self._catalog[item.data(_ID_ROLE)]
        dpr = self.devicePixelRatioF()
        thumb = svg_thumbnail(info.svg_path, PREVIEW_W, PREVIEW_H, dpr) if info.svg_path else None
        self._has_svg = thumb is not None
        self.preview.setPixmap(thumb or pedal_thumbnail(info.name, info.group, PREVIEW_W, PREVIEW_H, dpr))
        self.detail_name.setText(info.name)
        self.detail_facts.setText(f"{S.percent(info.dsp_load_percent)} · {S.slots_label(2 if info.is_wide else 1)}")
        self.detail.setText(effect_description(info))

    def preview_has_image(self) -> bool:
        """True when the preview is the effect's own SVG (a drawn stand-in does not count)."""
        return self._has_svg


def _wrapping_scroll(label: QLabel) -> QScrollArea:
    """A frameless, transparent vertical scroller for a word-wrapped label (no horizontal bar)."""
    scroll = QScrollArea()
    scroll.setWidget(label)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.viewport().setAutoFillBackground(False)
    return scroll
