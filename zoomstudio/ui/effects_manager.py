"""The "Efectos de la pedalera" screen: what is installed, what could be installed, memory and the two actions.

The screen only decides and asks; every pedal read and write is a request the window forwards to the
``PedalWorker`` (see ``install_requested`` / ``remove_requested`` / ``refresh_requested``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from zoomstudio.effects import flst
from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.effects.i18n import effect_description
from zoomstudio.effects.installer import MEMORY_MARGIN

from . import strings as S
from . import tokens
from .cards import (
    CARD_HEIGHT, FAVORITES_KEY, ROLE_DIRTY, ROLE_FAV, CHECK_ROOM, ROLE_CHECK, ROLE_MISSING, ROLE_NAME, ROLE_NUMBER, ROLE_SECTION, ROLE_STRIP, SECTION_HEIGHT,
    STAR_ROOM, PatchCardDelegate, check_rect, paint_check, SectionList, card_path, paint_section, paint_star, pedal_thumbnail, section_label,
    set_section_header, star_rect, svg_thumbnail, with_alpha,
)
from .dialogs import ConfirmDialog
from .favorites import FavoritesStore
from .fonts import display_font, ui_font
from .glass import BackdropRoot, GlassPanel
from .icons import icon, pixmap
from . import memory as memory_scale
from .painted import SearchField, SectionLabel
from .theme import group_color, group_fill_color, group_text_color

ROLE_ENTRY = Qt.ItemDataRole.UserRole + 30  # the Entry behind a card
ROLE_BADGE = Qt.ItemDataRole.UserRole + 32  # text of the badge on a card the pedal cannot install
ROLE_UNUSED = Qt.ItemDataRole.UserRole + 34  # tooltip of the «Sin uso» marker; None: the effect is in use or unknown
ROLE_MODELS = Qt.ItemDataRole.UserRole + 33  # «Para G11 · G6»: the models that can run this file (all-pedals views)
DETAIL_WIDTH = 360
BYPASS = "BYPASS.ZD2"  # the list's first record: the pedal's "no effect", not an effect to manage


@dataclass(frozen=True)
class Entry:
    """One effect of the pedal's list. ``info`` is None for effects the local catalog does not know."""

    file: str  # pedal file name, e.g. MDL_12ST.ZD2
    info: EffectInfo | None
    size: int | None  # bytes of the local .zd2
    missing: bool = False  # flagged installed in the list, but the file is not on the pedal
    compat: str = "ok"  # "ok", or why the connected pedal cannot install it: "model", "list" or "copy"

    @property
    def installable(self) -> bool:
        return self.compat == "ok"

    @property
    def name(self) -> str:
        return self.info.name if self.info is not None else Path(self.file).stem

    @property
    def group(self) -> str:
        return self.info.group if self.info is not None else "PEDAL"

    @property
    def dsp(self) -> float | None:
        return self.info.dsp_load_percent if self.info is not None else None

    @property
    def path(self) -> Path | None:
        return self.info.path if self.info is not None else None


def _local_size(path: Path | None) -> int | None:
    try:
        return path.stat().st_size if path is not None else None
    except OSError:
        return None


def build_entries(catalog: dict[int, EffectInfo], allowed_ids: set[int] | None, flst_bytes: bytes,
                  files: list[str]) -> tuple[list[Entry], list[Entry]]:
    """``(installed, available)`` for the pedal's list and file names.

    Installed: flag set in the first section of FLST_SEQ.ZT2; one whose file is not on the pedal is kept and marked
    ``missing`` so it can be repaired (only for effects the local catalog knows). Available: every other catalog
    effect, marked with why the connected pedal cannot install it (``compat``) when it cannot. Formerly: a catalog
    effect with a local .zd2, allowed on the A1 FOUR, that the list contains with its flag off.
    """
    on_pedal = set(files)
    by_file: dict[str, EffectInfo] = {}
    for info in sorted(catalog.values(), key=lambda e: (e.version, e.filename)):  # the newest version wins
        by_file[flst.pedal_filename(info.filename)] = info
    installed = []
    for file in flst.installed_names(flst_bytes):
        info = by_file.get(file)
        if file != BYPASS and (file in on_pedal or info is not None):  # a missing file of an unknown effect: nothing to show
            installed.append(Entry(file, info, _local_size(info.path if info else None), missing=file not in on_pedal))
    available = []
    flagged = {e.file for e in installed}
    for file, info in by_file.items():
        if file in flagged:
            continue
        size = _local_size(info.path)
        try:
            listed = not flst.is_installed(flst_bytes, file)  # in the list with its flag off: installable
        except flst.FlstError:
            listed = None  # the list does not contain it
        if allowed_ids is not None and info.effect_id not in allowed_ids:
            compat = "model"
        elif listed is None:
            compat = "list"
        elif size is None:
            compat = "copy"
        else:
            compat = "ok"
        available.append(Entry(file, info, size, compat=compat))
    key = lambda e: e.name.lower()  # noqa: E731
    return sorted(installed, key=key), sorted(available, key=key)


class EffectCard(QStyledItemDelegate):
    """An effect as a card: group monogram, name, DSP load, then group and the size of its file."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(1, SECTION_HEIGHT if index.data(ROLE_SECTION) else 60)  # the list stretches rows to its viewport

    def paint(self, p: QPainter, option, index) -> None:
        section = index.data(ROLE_SECTION)
        if section:
            paint_section(p, option, section)
            return
        entry: Entry = index.data(ROLE_ENTRY)
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
        p.setPen(QPen(with_alpha(tokens.color("accent"), 0.6) if selected else tokens.color("card-rim"),
                      1.5 if selected else 1))
        p.drawPath(path)
        ticked = index.data(ROLE_CHECK)
        shift = CHECK_ROOM if ticked is not None else 0
        if ticked is not None:
            paint_check(p, check_rect(option.rect), bool(ticked))
        mono = QRectF(rect.left() + 10 + shift, rect.center().y() - 21, 30, 42)
        p.setBrush(group_fill_color(entry.group))
        p.setPen(QPen(group_color(entry.group), 1.5))
        p.drawRoundedRect(mono, 7, 7)
        svg = entry.info.svg_path if entry.info is not None else None
        thumb = svg_thumbnail(svg, 30, 42, 1.0) if svg else None
        if thumb is not None:
            p.drawPixmap(mono.toRect(), thumb)
        else:
            p.setPen(group_text_color(entry.group))
            p.setFont(display_font(12, 600))
            p.drawText(mono, Qt.AlignmentFlag.AlignCenter, entry.name[:2].upper())
        left, right = mono.right() + 12, rect.right() - 12 - STAR_ROOM
        if index.data(ROLE_FAV) is not None:
            paint_star(p, star_rect(option.rect), bool(index.data(ROLE_FAV)), hover)
        dsp = S.percent(entry.dsp) if entry.dsp is not None else S.EFFECTS_DSP_NA
        dsp_w = QFontMetrics(ui_font(14)).horizontalAdvance(dsp)
        p.setFont(ui_font(15))
        p.setPen(tokens.color("text-primary"))
        name_rect = QRectF(left, rect.top() + 6, right - left - dsp_w - 8, 20)
        p.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(ui_font(15)).elidedText(entry.name, Qt.TextElideMode.ElideRight, int(name_rect.width())))
        p.setFont(ui_font(14))
        p.setPen(tokens.color("text-secondary"))
        p.drawText(QRectF(right - dsp_w, rect.top() + 6, dsp_w, 20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, dsp)
        p.setFont(ui_font(12))
        p.setPen(group_text_color(entry.group))
        line = QRectF(left, rect.top() + 29, right - left, 18)
        if entry.missing:  # a chip with text and an exclamation mark: not told by colour alone
            chip_text = "! " + S.EFFECTS_MISSING
            chip_w = QFontMetrics(ui_font(11)).horizontalAdvance(chip_text) + 14
            chip = QRectF(right - chip_w, rect.top() + 30, chip_w, 16)
            p.setPen(QPen(with_alpha(tokens.color("status-danger"), 0.8), 1))
            p.drawPath(card_path(chip, 8))
            p.setFont(ui_font(11))
            p.setPen(tokens.color("status-danger"))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, chip_text)
            p.setFont(ui_font(12))
            p.setPen(group_text_color(entry.group))
            line.setRight(chip.left() - 8)
        if index.data(ROLE_UNUSED):  # icon + «Sin uso»: shape and colour that no other chip or icon of the app has
            chip_w = QFontMetrics(ui_font(11)).horizontalAdvance(S.UNUSED) + 14 + 16
            chip = QRectF(right - chip_w, rect.top() + 30, chip_w, 16)
            color = tokens.color("status-ok")
            p.setPen(QPen(with_alpha(color, 0.8), 1))
            p.drawPath(card_path(chip, 8))
            p.drawPixmap(QPointF(chip.left() + 6, chip.top() + 2), pixmap("unused", color.name(), 12,
                                                                           p.device().devicePixelRatioF()))
            p.setFont(ui_font(11))
            p.setPen(color)
            p.drawText(chip.adjusted(18, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, S.UNUSED)
            p.setFont(ui_font(12))
            p.setPen(group_text_color(entry.group))
            line.setRight(chip.left() - 8)
        badge = index.data(ROLE_BADGE)
        if badge:  # not installable on the connected pedal: a chip with the words, not only a colour
            chip_w = QFontMetrics(ui_font(11)).horizontalAdvance(badge) + 14
            chip = QRectF(right - chip_w, rect.top() + 30, chip_w, 16)
            p.setPen(QPen(with_alpha(tokens.color("status-warn"), 0.8), 1))
            p.drawPath(card_path(chip, 8))
            p.setFont(ui_font(11))
            p.setPen(tokens.color("status-warn"))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, badge)
            p.setFont(ui_font(12))
            p.setPen(group_text_color(entry.group))
            line.setRight(chip.left() - 8)
        text = S.group_label(entry.group) if (entry.missing or badge) else f"{S.group_label(entry.group)} · {S.effects_size(entry.size)}"
        if index.data(ROLE_MODELS):  # a same-name variant is told apart by the models it is for
            text = f"{S.group_label(entry.group)} · {index.data(ROLE_MODELS)}"
        p.drawText(line, Qt.AlignmentFlag.AlignVCenter, QFontMetrics(ui_font(12)).elidedText(
            text, Qt.TextElideMode.ElideRight, int(line.width())))
        p.restore()


class _CardList(SectionList):
    """Effect cards grouped in sections (see ``SectionList``). A card with ``ROLE_CHECK`` has a tick box: a click on
    it, or Space, emits ``check_toggled``."""

    check_toggled = Signal(object)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        item = self.itemAt(event.position().toPoint())
        if (event.button() == Qt.MouseButton.LeftButton and item is not None and item.data(ROLE_CHECK) is not None
                and check_rect(self.visualItemRect(item)).adjusted(-4, -4, 4, 4).contains(event.position())):
            self.check_toggled.emit(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        item = self.currentItem()
        if event.key() == Qt.Key.Key_Space and item is not None and item.data(ROLE_CHECK) is not None:
            self.check_toggled.emit(item)
            event.accept()
            return
        super().keyPressEvent(event)

    def __init__(self) -> None:
        super().__init__()
        self.setItemDelegate(EffectCard(self))
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


class EffectsManager(GlassPanel):
    """Memory bar, the installed and available lists, a search field and the detail with the actions."""

    state_shown = Signal()  # the lists (or the offline message) were redrawn from fresh data
    refresh_requested = Signal()  # read the pedal's state again
    install_requested = Signal(str, object)  # pedal file name, local .zd2 path
    remove_requested = Signal(str)  # pedal file name
    remove_many_requested = Signal(object)  # «Quitar seleccionados»: the pedal file names, in removal order
    patch_requested = Signal(int)  # a patch card of «Usado en»: location to open in the editor
    repair_requested = Signal(str, object)  # pedal file name, local .zd2 path: upload only the missing file
    close_requested = Signal()
    update_requested = Signal()  # «Actualizar biblioteca…»: open the effect-library update view

    def __init__(self, root: BackdropRoot, catalog: dict[int, EffectInfo], allowed_ids: set[int] | None,
                 favorites: FavoritesStore | None = None) -> None:
        super().__init__(root)
        self.favorites = favorites if favorites is not None else FavoritesStore()
        self._catalog = catalog
        self._allowed = allowed_ids
        self._installed: list[Entry] = []
        self._available: list[Entry] = []
        self._free: int | None = None
        self._selected: str | None = None
        self._busy = False
        self._busy_text = ""
        self._loaded = False  # the lists show data read from the pedal
        self._patches_complete = False
        self._unsaved = False
        self._missing: dict[int, list[str]] = {}  # location -> effects the pedal lacks
        self._bank_uses: dict[str, int] = {}  # pedal file -> bank patches that use it
        self._checked: set[str] = set()  # unused effects ticked for «Quitar seleccionados»
        self._users: dict[str, list[tuple]] = {}  # file -> (display number, name, location, chain strip)
        self._collapsed: dict[str, set[str]] = {"installed": set(), "available": set()}  # kept while the screen lives

        self.close_button = QPushButton(S.EFFECTS_CLOSE)
        self.close_button.setIcon(icon("x"))
        self.close_button.clicked.connect(self.close_requested)
        self.update_button = QPushButton(S.UPDATE_BUTTON)
        self.update_button.setIcon(icon("reload"))
        self.update_button.setToolTip(S.UPDATE_BUTTON_TIP)
        self.update_button.clicked.connect(self.update_requested)
        self.update_button.hide()
        self.memory_bar = QProgressBar()
        self.memory_bar.setObjectName("effectsMemory")
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setTextVisible(False)  # the figures are their own label: text over a thin bar cannot be read
        self.memory_label = QLabel(S.NOT_AVAILABLE)
        self.memory_label.setProperty("role", "value")
        self.memory_icon = QLabel()  # a low or critical memory: icon and word beside the colour
        self.memory_icon.hide()
        self.memory_flag = QLabel("")
        self.memory_flag.hide()
        self.unused_link = QPushButton("")  # «5 efectos sin uso · 123 KB que se pueden liberar»: applies the filter
        self.unused_link.setFlat(True)
        self.unused_link.setProperty("link", True)
        self.unused_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unused_link.setIcon(icon("unused", "status-ok", 14))
        self.unused_link.clicked.connect(self.show_unused)
        self.unused_link.hide()
        self.unused_summary = QLabel("")
        self.unused_summary.setProperty("role", "secondary")
        self.select_all_button = QPushButton(S.SELECT_ALL)
        self.select_all_button.clicked.connect(self._on_select_all)
        self.remove_selected_button = QPushButton(S.remove_selected(0, 0))
        self.remove_selected_button.setProperty("danger", True)
        self.remove_selected_button.setIcon(icon("x", "status-danger"))
        self.remove_selected_button.clicked.connect(self._on_remove_selected)
        self.unused_bar = QWidget()
        bar = QHBoxLayout(self.unused_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(10)
        bar.addWidget(self.unused_summary, stretch=1)
        bar.addWidget(self.select_all_button)
        bar.addWidget(self.remove_selected_button)
        self.unused_bar.hide()
        self.message_label = QLabel("")
        self.message_label.setProperty("role", "offline")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry_button = QPushButton(S.EFFECTS_RETRY)
        self.retry_button.clicked.connect(self.refresh_requested)
        self.search = SearchField(S.SEARCH_EFFECTS, S.EFFECTS_SEARCH_TIP)
        self.search.textChanged.connect(lambda _text: self._populate())
        self.group_combo = QComboBox()
        self.group_combo.setToolTip(S.EFFECTS_GROUP_TIP)
        self.group_combo.setAccessibleName(S.EFFECTS_GROUP_TIP)
        self.group_combo.setMinimumWidth(190)
        self.group_combo.addItem(S.ALL_GROUPS, None)
        self.group_combo.addItem(S.FAVORITES, FAVORITES_KEY)
        self.group_combo.addItem(S.UNUSED, S.UNUSED_KEY)
        self.group_combo.currentIndexChanged.connect(lambda _i: self._populate())
        self.pedal_combo = QComboBox()  # which pedal's effects the right column lists (default: the connected one)
        self.pedal_combo.setToolTip(S.EFFECTS_PEDAL_TIP)
        self.pedal_combo.setAccessibleName(S.EFFECTS_PEDAL_TIP)
        self.pedal_combo.setMinimumWidth(170)
        self.pedal_combo.currentIndexChanged.connect(lambda _i: self._populate())
        self.pedal_combo.hide()
        self._models: dict = {}
        self._pedal_id: int | None = None  # the pedal the install flow is for (connected, else the target)
        self._pedal_connected = False  # ... and it is the real, connected one
        self._pedal_name = ""
        self._write_block: str | None = None  # why nothing may be written to the connected pedal
        self._flst_bytes: bytes | None = None
        self._files: list[str] = []

        self.installed_list, self.installed_count, self.installed_empty = _CardList(), QLabel(""), QLabel("")
        self.available_list, self.available_count, self.available_empty = _CardList(), QLabel(""), QLabel("")
        self.installed_list.itemSelectionChanged.connect(lambda: self._on_selection(self.installed_list))
        self.available_list.itemSelectionChanged.connect(lambda: self._on_selection(self.available_list))
        self.installed_list.section_toggled.connect(lambda item: self._toggle_item("installed", item))
        self.available_list.section_toggled.connect(lambda item: self._toggle_item("available", item))
        for cards in (self.installed_list, self.available_list):
            cards.favorite_toggled.connect(self._on_favorite_toggled)
        self.favorites.changed.connect(self._populate)
        self.installed_list.setAccessibleName(S.EFFECTS_INSTALLED)
        self.available_list.setAccessibleName(S.EFFECTS_AVAILABLE)

        self.detail_name = QLabel("")
        self.detail_name.setProperty("role", "heading")
        self.detail_name.setWordWrap(True)
        self.detail_facts = QLabel("")
        self.detail_facts.setProperty("role", "secondary")
        self.detail_facts.setWordWrap(True)
        self.preview = QLabel()
        self.preview.setFixedSize(64, 90)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_text = QLabel(S.EFFECTS_SELECT_HINT)
        self.detail_text.setProperty("role", "desc")
        self.detail_text.setWordWrap(True)
        self.detail_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detail_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        scroll = QScrollArea()
        scroll.setWidget(self.detail_text)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.reason_label = QLabel("")
        self.reason_label.setProperty("role", "reason")
        self.reason_label.setWordWrap(True)
        self.install_button = QPushButton(S.EFFECTS_INSTALL)
        self.install_button.setProperty("primary", True)
        self.install_button.setIcon(icon("plus", "on-accent"))
        self.remove_button = QPushButton(S.EFFECTS_REMOVE)
        self.remove_button.setProperty("danger", True)
        self.remove_button.setIcon(icon("x", "status-danger"))
        self.repair_button = QPushButton(S.EFFECTS_REPAIR)
        self.repair_button.setProperty("primary", True)
        self.repair_button.setIcon(icon("reload", "on-accent"))
        self.repair_button.clicked.connect(self._on_repair)
        self.usage_title = QLabel("")
        self.usage_title.setProperty("role", "strong")
        self.usage_list = QListWidget()
        self.usage_list.setItemDelegate(PatchCardDelegate(self.usage_list))
        self.usage_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.usage_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.usage_list.setMouseTracking(True)
        self.usage_list.setAccessibleName(S.EFFECTS_USAGE_LIST)
        self.usage_list.itemClicked.connect(self._on_usage_card)
        self.usage_list.itemActivated.connect(self._on_usage_card)
        self.usage_note = QLabel("")
        self.usage_note.setProperty("role", "secondary")
        self.usage_note.setWordWrap(True)
        self.usage_empty_icon = QLabel()
        self.usage_empty_icon.setPixmap(icon("check", "text-secondary", 22).pixmap(22, 22))
        self.usage_empty_note = QLabel(S.EFFECTS_USAGE_NONE_NOTE)
        self.usage_empty_note.setProperty("role", "secondary")
        self.usage_empty_note.setWordWrap(True)
        self.usage_empty = QWidget()
        empty = QHBoxLayout(self.usage_empty)
        empty.setContentsMargins(4, 2, 0, 2)
        empty.setSpacing(10)
        empty.addWidget(self.usage_empty_icon, alignment=Qt.AlignmentFlag.AlignTop)
        empty.addWidget(self.usage_empty_note, stretch=1)
        self.usage_box = QWidget()
        usage = QVBoxLayout(self.usage_box)
        usage.setContentsMargins(0, 0, 0, 0)
        usage.setSpacing(6)
        usage.addWidget(self.usage_title)
        usage.addWidget(self.usage_list)
        usage.addWidget(self.usage_empty)
        usage.addWidget(self.usage_note)
        self.usage_box.hide()
        self.install_button.clicked.connect(self._on_install)
        self.remove_button.clicked.connect(self._on_remove)
        self.installed_list.check_toggled.connect(lambda item: self.set_checked(
            item.data(ROLE_ENTRY).file, not item.data(ROLE_CHECK)))

        title = QHBoxLayout()
        title.addWidget(SectionLabel(S.EFFECTS_TITLE))
        title.addStretch(1)
        title.addWidget(self.update_button)
        title.addWidget(self.close_button)
        memory = QHBoxLayout()
        memory.setSpacing(12)
        memory.addWidget(QLabel(S.MEMORY_LABEL))
        memory.addWidget(self.memory_bar, stretch=1)
        memory.addWidget(self.memory_icon)
        memory.addWidget(self.memory_flag)
        memory.addWidget(self.memory_label)
        memory.addWidget(self.unused_link)

        self.content = QWidget()
        content = QHBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        lists = QVBoxLayout()
        filters = QHBoxLayout()
        filters.setSpacing(10)
        filters.addWidget(self.search, stretch=1)
        filters.addWidget(self.group_combo)
        filters.addWidget(self.pedal_combo)
        lists.addLayout(filters)
        lists.addWidget(self.unused_bar)
        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addLayout(self._column(S.EFFECTS_INSTALLED, self.installed_count, self.installed_empty,
                                       self.installed_list))
        columns.addLayout(self._column(S.EFFECTS_AVAILABLE, self.available_count, self.available_empty,
                                       self.available_list))
        lists.addLayout(columns, stretch=1)
        detail = QWidget()
        detail.setFixedWidth(DETAIL_WIDTH)
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.addWidget(self.detail_name)
        names.addWidget(self.detail_facts)
        names.addStretch(1)
        head.addLayout(names, stretch=1)
        dl.addLayout(head)
        dl.addWidget(scroll, stretch=1)
        dl.addWidget(self.usage_box)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reason_label, stretch=1)
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.repair_button)
        buttons.addWidget(self.install_button)
        dl.addLayout(buttons)
        content.addLayout(lists, stretch=1)
        content.addWidget(detail)

        self.message_box = QWidget()
        mb = QVBoxLayout(self.message_box)
        mb.addStretch(1)
        mb.addWidget(self.message_label)
        mb.addWidget(self.retry_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        mb.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(12)
        lay.addLayout(title)
        lay.addLayout(memory)
        lay.addWidget(self.content, stretch=1)
        lay.addWidget(self.message_box, stretch=1)
        self.set_offline()

    @staticmethod
    def _column(title: str, count: QLabel, empty: QLabel, cards: QListWidget) -> QVBoxLayout:
        count.setProperty("role", "secondary")
        empty.setProperty("role", "secondary")
        empty.setWordWrap(True)
        header = QHBoxLayout()
        header.addWidget(SectionLabel(title))
        header.addStretch(1)
        header.addWidget(count)
        column = QVBoxLayout()
        column.addLayout(header)
        column.addWidget(empty)
        column.addWidget(cards, stretch=1)
        return column

    # ------------------------------------------------------------ what the screen shows

    def installed_names(self) -> list[str]:
        return self._file_names(self.installed_list)

    def available_names(self) -> list[str]:
        return self._file_names(self.available_list)

    @staticmethod
    def _file_names(cards: QListWidget) -> list[str]:
        return [cards.item(i).data(ROLE_ENTRY).file for i in range(cards.count())
                if cards.item(i).data(ROLE_ENTRY) is not None]

    def missing_names(self) -> list[str]:
        """Installed effects whose file is not on the pedal."""
        return [e.file for e in self._installed if e.missing]

    def section_groups(self, which: str) -> list[str]:
        """The groups of ``which`` ("installed" or "available") that have a section, in screen order."""
        return [item.data(ROLE_SECTION)[0] for item in self._headers(which)]

    def section_count(self, which: str, group: str) -> int:
        return self._header(which, group).data(ROLE_SECTION)[1]

    def section_expanded(self, which: str, group: str) -> bool:
        return self._header(which, group).data(ROLE_SECTION)[2]

    def section_header_row(self, which: str, group: str) -> int:
        return self._list(which).row(self._header(which, group))

    def toggle_section(self, which: str, group: str) -> None:
        self._toggle_item(which, self._header(which, group))

    def _list(self, which: str) -> QListWidget:
        return self.installed_list if which == "installed" else self.available_list

    def _headers(self, which: str) -> list[QListWidgetItem]:
        cards = self._list(which)
        return [cards.item(i) for i in range(cards.count()) if cards.item(i).data(ROLE_SECTION)]

    def _header(self, which: str, group: str) -> QListWidgetItem:
        return next(item for item in self._headers(which) if item.data(ROLE_SECTION)[0] == group)

    def _toggle_item(self, which: str, header: QListWidgetItem) -> None:
        group, _count, expanded = header.data(ROLE_SECTION)
        collapsed = self._collapsed[which]
        collapsed.discard(group) if not expanded else collapsed.add(group)
        self._list(which).set_section_expanded(header, not expanded)

    @staticmethod
    def _set_section(which: str, header: QListWidgetItem, group: str, count: int, expanded: bool) -> None:
        set_section_header(header, group, count, expanded)

    def selected_name(self) -> str | None:
        return self._selected

    def description_of(self, file: str) -> str:
        entry = self._entry(file)
        return effect_description(entry.info) if entry is not None and entry.info is not None else S.EFFECTS_NO_DESCRIPTION

    def _entry(self, file: str | None) -> Entry | None:
        return next((e for e in self._installed + self._available if e.file == file), None)

    def _show_message(self, text: str, retry: bool = False) -> None:
        self.message_label.setText(text)
        self.retry_button.setVisible(retry)
        self.message_box.show()
        self.content.hide()

    def set_offline(self) -> None:
        """No pedal: nothing to show or install."""
        self._loaded = False
        self._installed, self._available, self._free, self._selected = [], [], None, None
        self.memory_bar.setValue(0)
        self.memory_label.setText(S.NOT_AVAILABLE)
        memory_scale.apply_state(self.memory_bar, self.memory_icon, self.memory_flag, (self.memory_label,), None)
        self._populate()
        self._show_message(S.EFFECTS_OFFLINE)
        self.state_shown.emit()

    def set_loading(self) -> None:
        self._loaded = False
        self._show_message(S.EFFECTS_LOADING)
        self._update_actions()

    def set_failed(self) -> None:
        """The state could not be read; the error itself went through the window's error path."""
        self._loaded = False
        self._show_message(S.EFFECTS_LOAD_FAILED, retry=True)
        self._update_actions()

    def set_pedals(self, models: dict, pedal_id: int | None, connected: bool, allowed_ids: set[int] | None) -> None:
        """The pedal models Guitar Lab lists and the one effects are installed on (``connected``: it is the real one).

        The filter offers that pedal first (named after its ``modelName``), then every pedal, then the others.
        """
        self._models, self._pedal_id, self._allowed = models, pedal_id, allowed_ids
        self._pedal_connected = connected
        known = models.get(pedal_id)
        self._pedal_name = known.name if known is not None else ""
        chosen = self.pedal_combo.currentData()
        self.pedal_combo.blockSignals(True)
        self.pedal_combo.clear()
        if known is not None:
            self.pedal_combo.addItem(S.pedal_connected_label(known.name) if connected else known.name, pedal_id)
            self.pedal_combo.addItem(S.EFFECTS_ALL_PEDALS, "all")
            for model in sorted(models.values(), key=lambda m: m.name):
                if model.model_id != pedal_id:
                    self.pedal_combo.addItem(model.name, model.model_id)
            index = self.pedal_combo.findData(chosen)
            self.pedal_combo.setCurrentIndex(max(index, 0))
        self.pedal_combo.blockSignals(False)
        self.pedal_combo.setVisible(known is not None)
        if self._flst_bytes is not None and self._loaded:
            self._rebuild()
        else:
            self._populate()

    def _rebuild(self) -> None:
        try:
            self._installed, self._available = build_entries(self._catalog, self._allowed, self._flst_bytes, self._files)
        except flst.FlstError:
            return
        self._refill_groups()
        self._populate()

    def set_state(self, flst_bytes: bytes, files: list[str], usage) -> None:
        self._flst_bytes, self._files = flst_bytes, list(files)
        try:
            installed, available = build_entries(self._catalog, self._allowed, flst_bytes, files)
        except flst.FlstError:
            self.set_failed()
            return
        self._loaded = True
        self._installed, self._available = installed, available
        self._free = usage.available
        self.memory_bar.setValue(round(usage.used_percent))
        self.memory_label.setText(S.effects_memory(usage.used, usage.maximum, usage.available))
        memory_scale.apply_state(self.memory_bar, self.memory_icon, self.memory_flag, (self.memory_label,), usage.available)
        self.message_box.hide()
        self.content.show()
        self._refill_groups()
        self._populate()
        self.state_shown.emit()

    def set_patch_usage(self, complete: bool, unsaved: bool, users: dict[str, list[tuple]],
                        missing: dict[int, list[str]] | None = None, bank_uses: dict[str, int] | None = None) -> None:
        """What the editor knows: every patch read, any unsaved edit, and the patches (number, name) using each file.

        ``missing``: location -> the effects of that patch the pedal lacks (its card carries the amber warning)."""
        self._patches_complete, self._unsaved, self._users = complete, unsaved, users
        self._missing = dict(missing or {})
        self._bank_uses = dict(bank_uses or {})
        if self._loaded:
            self._populate()  # the «Sin uso» markers follow what the patches use
        else:
            self._update_actions()

    def set_write_block(self, reason: str | None) -> None:
        """A pedal the app cannot edit yet: browse and read, but install, remove and repair stay off."""
        self._write_block = reason
        self._update_actions()

    def set_update_available(self, available: bool) -> None:
        """The window has an updater: show the «Actualizar biblioteca…» button."""
        self.update_button.setVisible(available)

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self._busy_text = text
        self.search.setEnabled(not busy)
        self.group_combo.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        self.update_button.setEnabled(not busy)
        self.installed_list.setEnabled(not busy)
        self.available_list.setEnabled(not busy)
        self._update_actions()

    # ------------------------------------------------------------ lists and selection

    def _in_pedal_filter(self, entry: Entry) -> bool:
        """The right column lists the effects of the chosen pedal (every one for «Todos los pedales»)."""
        choice = self.pedal_combo.currentData()
        if choice is None or choice == "all" or entry.info is None:
            return True
        model = self._models.get(choice)
        if model is None or entry.info.effect_id not in model.effect_ids:
            return model is None
        if self._pedal_connected and choice == self._pedal_id:
            # the connected pedal's own view lists what it can take: another model's variant, or an effect its list has
            # no record of (it never installs), would only look like a second, incompatible copy of an installed one
            return entry.compat in ("ok", "copy")
        return True

    def _connected_view(self) -> bool:
        return self._pedal_connected and self.pedal_combo.currentData() == self._pedal_id

    def _models_line(self, entry: Entry) -> str | None:
        """«Para G11 · G6 · H8»: shown where several pedals' effects mix, so same-name variants can be told apart."""
        if entry.info is None or self._connected_view() or not self._models:
            return None
        names = sorted(m.name for m in self._models.values() if entry.info.effect_id in m.effect_ids)
        return S.effects_for_models(names) if names else None

    def _entry_tip(self, entry: Entry, reason: str = "") -> str:
        """Tooltip: why it cannot be installed (if so), its pedal file name, and an installed same-name version."""
        lines = [reason] if reason else []
        lines.append(entry.file)
        twin = next((e for e in self._installed if e.file != entry.file and e.name == entry.name), None)
        if twin is not None and entry not in self._installed:
            lines.append(S.effects_other_version_installed(entry.name, twin.file))
        return "\n".join(lines)

    def _matches(self, entry: Entry, query: str, apply_pedal: bool = False) -> bool:
        if apply_pedal and not self._in_pedal_filter(entry):
            return False
        haystack = f"{entry.name} {entry.file} {entry.group} {S.group_label(entry.group)}".lower()
        group = self.group_combo.currentData()
        if group == FAVORITES_KEY:
            if not self._is_favorite(entry):
                return False
        elif group == S.UNUSED_KEY:
            if not self._is_unused(entry):
                return False
        elif group is not None and entry.group != group:
            return False
        return all(word in haystack for word in query.lower().split())

    # ------------------------------------------------------------ «Sin uso»

    def _usage_confirmed(self) -> bool:
        """What Quitar already requires: every patch read and no unsaved edit."""
        return self._loaded and self._patches_complete and not self._unsaved

    def _is_unused(self, entry: Entry) -> bool:
        """Installed, its file on the pedal, known to the catalog, and no patch of the pedal uses it (never a guess)."""
        return (self._usage_confirmed() and entry.info is not None and not entry.missing
                and entry in self._installed and not self._users.get(entry.file))

    def _unused_view(self) -> bool:
        return self.group_combo.currentData() == S.UNUSED_KEY

    def show_unused(self) -> None:
        self.group_combo.setCurrentIndex(self.group_combo.findData(S.UNUSED_KEY))

    def _unused_tip(self, entry: Entry) -> str:
        uses = self._bank_uses.get(entry.file, 0)
        return S.UNUSED_TIP + (f". {S.unused_bank_note(uses)}" if uses else "")

    def checked_names(self) -> list[str]:
        """The ticked unused effects (pedal file names) in the order the list shows them."""
        return [f for f in self.installed_names() if f in self._checked]

    def set_checked(self, file: str, on: bool) -> bool:
        """Tick or untick an unused effect; an effect in use (or one nothing is known about) can never be ticked."""
        entry = self._entry(file)
        if entry is None or not self._is_unused(entry):
            return False
        (self._checked.add if on else self._checked.discard)(file)
        for i in range(self.installed_list.count()):
            item = self.installed_list.item(i)
            if item.data(ROLE_ENTRY) is not None and item.data(ROLE_ENTRY).file == file and item.data(ROLE_CHECK) is not None:
                item.setData(ROLE_CHECK, on)
        self.installed_list.viewport().update()
        self._update_unused_ui()
        return True

    def _shown_unused(self) -> list[Entry]:
        return [self.installed_list.item(i).data(ROLE_ENTRY) for i in range(self.installed_list.count())
                if self.installed_list.item(i).data(ROLE_ENTRY) is not None
                and self._is_unused(self.installed_list.item(i).data(ROLE_ENTRY))]

    def _on_select_all(self) -> None:
        shown = self._shown_unused()
        everything = all(e.file in self._checked for e in shown)
        for entry in shown:
            self.set_checked(entry.file, not everything)

    def _update_unused_ui(self) -> None:
        """The link in the default view, and the summary and the two buttons of the «Sin uso» view."""
        unused = [e for e in self._installed if self._is_unused(e)]
        in_view = self._unused_view()
        self.unused_link.setVisible(bool(unused) and not in_view and self._usage_confirmed())
        self.unused_link.setText(S.unused_summary(len(unused), sum(e.size or 0 for e in unused)))
        self.unused_bar.setVisible(in_view)
        if not in_view:
            return
        shown = self._shown_unused()
        self.unused_summary.setText(S.unused_summary(len(shown), sum(e.size or 0 for e in shown))
                                    if self._usage_confirmed() else S.UNUSED_UNKNOWN)
        ticked = [e for e in shown if e.file in self._checked]
        self.remove_selected_button.setText(S.remove_selected(len(ticked), sum(e.size or 0 for e in ticked)))
        reason = self._write_block or (S.UNUSED_UNKNOWN if not self._usage_confirmed() else "")
        self.remove_selected_button.setEnabled(bool(ticked) and not reason and not self._busy)
        self.remove_selected_button.setToolTip(reason)
        self.select_all_button.setEnabled(bool(shown) and not self._busy)

    def _on_remove_selected(self) -> None:
        ticked = [e for e in self._shown_unused() if e.file in self._checked]
        if not ticked or not self.remove_selected_button.isEnabled():
            return
        lines = []
        for e in ticked:
            uses = self._bank_uses.get(e.file, 0)
            lines.append(f"{e.name} ({e.file}, {S.effects_size(e.size)})" + (f" · {S.unused_bank_note(uses)}" if uses else ""))
        if ConfirmDialog.ask(self, S.remove_many_title(len(ticked)),
                             S.effects_confirm_remove_many(lines, sum(e.size or 0 for e in ticked)),
                             S.EFFECTS_REMOVE, danger=True):
            self.remove_many_requested.emit([e.file for e in ticked])

    def _refill_groups(self) -> None:
        """The group filter offers the groups of the pedal's effects, in the catalog's order; the choice survives."""
        chosen = self.group_combo.currentData()
        groups = sorted({e.group for e in self._installed + self._available})
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem(S.ALL_GROUPS, None)
        self.group_combo.addItem(S.FAVORITES, FAVORITES_KEY)
        self.group_combo.addItem(S.UNUSED, S.UNUSED_KEY)
        for group in groups:
            self.group_combo.addItem(S.group_label(group), group)
        index = self.group_combo.findData(chosen)
        self.group_combo.setCurrentIndex(max(index, 0))
        self.group_combo.blockSignals(False)

    def _populate(self) -> None:
        query = self.search.text().strip()
        for which, cards, entries, count, empty, none_text in (
                ("installed", self.installed_list, self._installed, self.installed_count, self.installed_empty,
                 S.EFFECTS_NONE_INSTALLED),
                ("available", self.available_list, self._available, self.available_count, self.available_empty,
                 S.EFFECTS_NONE_AVAILABLE)):
            shown = [e for e in entries if self._matches(e, query, apply_pedal=which == "available")]
            flat = self._unused_view() and which == "installed"  # the «Sin uso» view: one list, the largest first
            if self._unused_view() and which == "available":
                shown = []
            if flat:
                shown.sort(key=lambda e: (-(e.size or 0), e.name.lower()))
            total = len([e for e in entries if which == "installed" or self._in_pedal_filter(e)])
            cards.blockSignals(True)
            cards.clear()
            def section_of(e: Entry) -> str:
                return FAVORITES_KEY if self._is_favorite(e) else e.group  # a favourite lives in its own section only

            sections = ([(None, shown)] if flat else
                        [(g, [e for e in shown if section_of(e) == g])
                         for g in sorted({section_of(e) for e in shown}, key=lambda g: (g != FAVORITES_KEY, g))])
            for group, section in sections:
                folded = group is not None and group in self._collapsed[which]
                if group is not None:
                    header = QListWidgetItem()
                    self._set_section(which, header, group, len(section), not folded)
                    cards.addItem(header)
                for entry in section:
                    item = QListWidgetItem()
                    item.setData(ROLE_ENTRY, entry)
                    if which == "available":
                        item.setData(ROLE_MODELS, self._models_line(entry))
                        item.setToolTip(self._entry_tip(entry))
                        item.setData(Qt.ItemDataRole.AccessibleTextRole,
                                     f"{entry.name}, {item.toolTip().replace(chr(10), ', ')}")
                    item.setData(ROLE_FAV, self._is_favorite(entry) if entry.info is not None else None)
                    if not entry.installable:
                        badge = S.not_compatible_with(self._pedal_name) if self._pedal_name else S.EFFECTS_NOT_INSTALLABLE
                        tip = badge
                        if entry.compat == "list":  # its model fits, but the pedal's list has no record of it
                            badge, tip = S.EFFECTS_LIST_BADGE, S.EFFECTS_NOT_IN_LIST_TIP
                        item.setData(ROLE_BADGE, badge)
                        full = self._entry_tip(entry, tip)
                        item.setToolTip(full)
                        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{entry.name}, {full.replace(chr(10), ', ')}")
                    if entry.missing:
                        item.setToolTip(S.EFFECTS_MISSING_TIP)
                        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{entry.name}, {S.EFFECTS_MISSING_TIP}")
                    if which == "installed" and self._is_unused(entry):
                        tip = self._unused_tip(entry)
                        item.setData(ROLE_UNUSED, tip)
                        item.setToolTip(tip)
                        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{entry.name}, {S.UNUSED}. {tip}")
                    if flat:
                        item.setData(ROLE_CHECK, entry.file in self._checked)
                    item.setHidden(folded)
                    cards.addItem(item)
                    if entry.file == self._selected:
                        cards.setCurrentItem(item)
            cards.blockSignals(False)
            count.setText(S.effects_count(len(shown), total))
            empty.setText(S.UNUSED_VIEW_NOTE if self._unused_view() and which == "available" else none_text)
            empty.setVisible(not shown)
        self._checked &= {e.file for e in self._installed if self._is_unused(e)}  # only unused ones stay ticked
        if self._entry(self._selected) is None:
            self._selected = None
        self._show_detail()
        self._update_unused_ui()

    def select_effect(self, file: str) -> None:
        """Select the card of ``file`` in whichever list shows it."""
        for which in ("installed", "available"):
            cards = self._list(which)
            for i in range(cards.count()):
                entry = cards.item(i).data(ROLE_ENTRY)
                if entry is not None and entry.file == file:
                    section = FAVORITES_KEY if self._is_favorite(entry) else entry.group
                    if section in self._collapsed[which]:
                        self.toggle_section(which, section)  # a selection must be visible
                    cards.setCurrentRow(i)
                    return

    def _on_favorite_toggled(self, item: QListWidgetItem) -> None:
        entry = item.data(ROLE_ENTRY)
        if entry is not None and entry.info is not None:
            self.favorites.toggle(entry.info.effect_id)

    def _is_favorite(self, entry: Entry) -> bool:
        return entry.info is not None and self.favorites.is_favorite(entry.info.effect_id)

    def _on_selection(self, cards: QListWidget) -> None:
        item = cards.currentItem() if cards.selectedItems() else None
        if item is None or item.data(ROLE_ENTRY) is None:  # nothing, or a section header
            return
        other = self.available_list if cards is self.installed_list else self.installed_list
        other.blockSignals(True)
        other.clearSelection()
        other.setCurrentRow(-1)
        other.blockSignals(False)
        self._selected = item.data(ROLE_ENTRY).file
        self._show_detail()

    def _show_detail(self) -> None:
        entry = self._entry(self._selected)
        if entry is None:
            self.detail_name.setText("")
            self.detail_facts.setText("")
            self.preview.clear()
            self.detail_text.setText(S.EFFECTS_SELECT_HINT)
        else:
            self.detail_name.setText(entry.name)
            dsp = S.percent(entry.dsp) if entry.dsp is not None else S.EFFECTS_DSP_NA
            self.detail_facts.setText(S.effects_facts(S.group_label(entry.group), dsp, S.effects_size(entry.size)))
            self.detail_text.setText(self.description_of(entry.file))
            svg = entry.info.svg_path if entry.info is not None else None
            thumb = svg_thumbnail(svg, 64, 90, self.devicePixelRatioF()) if svg else None
            self.preview.setPixmap(thumb or pedal_thumbnail(entry.name, entry.group, 64, 90, self.devicePixelRatioF()))
        self._update_actions()

    # ------------------------------------------------------------ where the effect is used

    def usage_locations(self) -> list[int]:
        return [self.usage_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.usage_list.count())]

    def _on_usage_card(self, item: QListWidgetItem) -> None:
        self.patch_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _update_usage(self) -> None:
        """«Usado en N patches» as small patch cards; a calm message when none, a neutral note when unconfirmed."""
        entry = self._entry(self._selected)
        show = entry is not None and self._loaded and not any(e.file == entry.file for e in self._available)
        self.usage_box.setVisible(show)
        if not show:
            return
        confirmed = self._patches_complete and not self._unsaved
        users = self._users.get(entry.file, []) if confirmed else []
        self.usage_list.clear()
        for display, name, location, strip in users:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, location)
            item.setData(ROLE_NUMBER, display)
            item.setData(ROLE_NAME, name)
            item.setData(ROLE_STRIP, strip)
            item.setData(ROLE_DIRTY, False)
            lacking = self._missing.get(location)
            spoken = S.effects_usage_card_name(display, name) + (f". {S.patch_missing_tip(lacking)}" if lacking else "")
            item.setData(ROLE_MISSING, lacking)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, spoken)
            item.setToolTip(spoken)
            self.usage_list.addItem(item)
        self.usage_list.setFixedHeight(min(len(users), 3) * CARD_HEIGHT + 4)
        if not confirmed:
            self.usage_title.setText(S.EFFECTS_USAGE_PENDING_TITLE)
            self.usage_note.setText(S.EFFECTS_PATCHES_INCOMPLETE if not self._patches_complete
                                    else S.EFFECTS_UNSAVED_PATCHES)
        else:
            self.usage_title.setText(S.effects_usage_title(len(users)) if users else S.EFFECTS_USAGE_NONE)
        self.usage_note.setVisible(not confirmed)
        self.usage_list.setVisible(confirmed and bool(users))
        self.usage_empty.setVisible(confirmed and not users)

    # ------------------------------------------------------------ actions

    def _update_actions(self) -> None:
        entry = self._entry(self._selected)
        installing = entry is not None and any(e.file == entry.file for e in self._available)
        repairing = entry is not None and entry.missing
        removing = entry is not None and not installing and not repairing
        self.install_button.setVisible(installing)
        self.remove_button.setVisible(removing)
        self.repair_button.setVisible(repairing)
        enabled, reason, blocking = False, "", False
        if entry is None or not self._loaded:
            pass
        elif self._busy:
            reason = self._busy_text
        elif repairing:
            need = (entry.size or 0) + MEMORY_MARGIN
            if entry.path is None or entry.size is None:
                reason, blocking = S.EFFECTS_NO_LOCAL_COPY, True
            elif self._free is None or need > self._free:
                reason, blocking = S.effects_install_blocked(need, entry.size, MEMORY_MARGIN, self._free or 0), True
            else:
                enabled, reason = True, S.EFFECTS_REPAIR_OK
        elif installing and not entry.installable:  # shown, with its description and star, but not installable
            reason = (S.effects_not_compatible_reason(self._pedal_name or S.EFFECTS_THIS_PEDAL) if entry.compat == "model"
                      else S.EFFECTS_NOT_IN_PEDAL_LIST if entry.compat == "list" else S.EFFECTS_NO_LOCAL_COPY)
        elif installing:
            need = (entry.size or 0) + MEMORY_MARGIN
            if self._free is None or entry.size is None or need > self._free:
                reason = S.effects_install_blocked(need, entry.size or 0, MEMORY_MARGIN, self._free or 0)
                blocking = True
            else:
                enabled, reason = True, S.EFFECTS_INSTALL_OK
        else:
            enabled, reason = False, ""
            if entry.info is None:
                reason = S.EFFECTS_NOT_IN_CATALOG
            elif not self._patches_complete or self._unsaved:
                reason = S.EFFECTS_USAGE_PENDING_SHORT
            elif self._users.get(entry.file):
                reason = S.EFFECTS_IN_USE_SHORT
            else:
                enabled, reason = True, S.EFFECTS_REMOVE_OK
        if self._write_block and entry is not None and self._loaded and not self._busy:
            enabled = False
            if enabled is False and not (installing and not entry.installable):
                reason = self._write_block  # a non compatible card keeps its own, more specific reason
        self.install_button.setEnabled(enabled and installing)
        self.remove_button.setEnabled(enabled and removing)
        self.repair_button.setEnabled(enabled and repairing)
        self._update_usage()
        self.reason_label.setText(reason)
        self.reason_label.setProperty("blocking", blocking)
        self.reason_label.style().unpolish(self.reason_label)
        self.reason_label.style().polish(self.reason_label)
        tip = reason if reason else ""
        self.install_button.setToolTip(tip)
        self.remove_button.setToolTip(tip)
        self.repair_button.setToolTip(tip)
        self._update_unused_ui()

    def _on_install(self) -> None:
        entry = self._entry(self._selected)
        if entry is None or entry.path is None or entry.size is None or not self.install_button.isEnabled():
            return
        if self.confirm_install(entry):
            self.install_requested.emit(entry.file, entry.path)

    def confirm_install(self, entry: Entry, parent: QWidget | None = None) -> bool:
        """The install confirmation (file, size, backup note, free memory); the editor's quick install asks it too."""
        return ConfirmDialog.ask(parent or self, S.effects_confirm_install_title(entry.name),
                                 S.effects_confirm_install(entry.name, entry.file, entry.size or 0, self._free or 0),
                                 S.EFFECTS_INSTALL)

    def confirm_repair(self, entry: Entry, parent: QWidget | None = None) -> bool:
        return ConfirmDialog.ask(parent or self, S.effects_confirm_repair_title(entry.name),
                                 S.effects_confirm_repair(entry.name, entry.file, entry.size or 0, self._free or 0),
                                 S.EFFECTS_REPAIR)

    def _on_repair(self) -> None:
        entry = self._entry(self._selected)
        if entry is None or entry.path is None or entry.size is None or not self.repair_button.isEnabled():
            return
        if self.confirm_repair(entry):
            self.repair_requested.emit(entry.file, entry.path)

    def _on_remove(self) -> None:
        entry = self._entry(self._selected)
        if entry is None or not self.remove_button.isEnabled():
            return
        if ConfirmDialog.ask(self, S.effects_confirm_remove_title(entry.name),
                             S.effects_confirm_remove(entry.name, entry.file, self._bank_uses.get(entry.file, 0)),
                             S.EFFECTS_REMOVE, danger=True):
            self.remove_requested.emit(entry.file)
