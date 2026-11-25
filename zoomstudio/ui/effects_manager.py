"""The "Efectos de la pedalera" screen: what is installed, what could be installed, memory and the two actions.

The screen only decides and asks; every pedal read and write is a request the window forwards to the
``PedalWorker`` (see ``install_requested`` / ``remove_requested`` / ``refresh_requested``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from zoomstudio.effects import flst
from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.effects.i18n import effect_description
from zoomstudio.effects.installer import MEMORY_MARGIN

from . import strings as S
from . import tokens
from .cards import card_path, pedal_thumbnail, svg_thumbnail, with_alpha
from .dialogs import ConfirmDialog
from .fonts import display_font, ui_font
from .glass import BackdropRoot, GlassPanel
from .icons import icon
from .painted import SectionLabel
from .theme import group_color, group_fill_color, group_text_color

ROLE_ENTRY = Qt.ItemDataRole.UserRole + 30  # the Entry behind a card
DETAIL_WIDTH = 360
BYPASS = "BYPASS.ZD2"  # the list's first record: the pedal's "no effect", not an effect to manage


@dataclass(frozen=True)
class Entry:
    """One effect of the pedal's list. ``info`` is None for effects the local catalog does not know."""

    file: str  # pedal file name, e.g. MDL_12ST.ZD2
    info: EffectInfo | None
    size: int | None  # bytes of the local .zd2

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

    Installed: flag set in the first section of FLST_SEQ.ZT2 and the file is on the pedal. Available: a catalog
    effect with a local .zd2, allowed on the A1 FOUR, that the list contains with its flag off.
    """
    on_pedal = set(files)
    by_file: dict[str, EffectInfo] = {}
    for info in sorted(catalog.values(), key=lambda e: (e.version, e.filename)):  # the newest version wins
        by_file[flst.pedal_filename(info.filename)] = info
    installed = []
    for file in flst.installed_names(flst_bytes):
        if file != BYPASS and file in on_pedal:
            info = by_file.get(file)
            installed.append(Entry(file, info, _local_size(info.path if info else None)))
    available = []
    for file, info in by_file.items():
        if info.path is None or (allowed_ids is not None and info.effect_id not in allowed_ids):
            continue
        try:
            listed_off = not flst.is_installed(flst_bytes, file)
        except flst.FlstError:
            continue  # the list does not contain it: the pedal cannot install it
        size = _local_size(info.path)
        if listed_off and size is not None:
            available.append(Entry(file, info, size))
    key = lambda e: e.name.lower()  # noqa: E731
    return sorted(installed, key=key), sorted(available, key=key)


class EffectCard(QStyledItemDelegate):
    """An effect as a card: group monogram, name, DSP load, then group and the size of its file."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(option.rect.width(), 60)

    def paint(self, p: QPainter, option, index) -> None:
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
        mono = QRectF(rect.left() + 10, rect.center().y() - 21, 30, 42)
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
        left, right = mono.right() + 12, rect.right() - 12
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
        p.drawText(QRectF(left, rect.top() + 29, right - left, 18), Qt.AlignmentFlag.AlignVCenter,
                   f"{S.group_label(entry.group)} · {S.effects_size(entry.size)}")
        p.restore()


class _CardList(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setItemDelegate(EffectCard(self))
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)


class EffectsManager(GlassPanel):
    """Memory bar, the installed and available lists, a search field and the detail with the actions."""

    state_shown = Signal()  # the lists (or the offline message) were redrawn from fresh data
    refresh_requested = Signal()  # read the pedal's state again
    install_requested = Signal(str, object)  # pedal file name, local .zd2 path
    remove_requested = Signal(str)  # pedal file name
    close_requested = Signal()

    def __init__(self, root: BackdropRoot, catalog: dict[int, EffectInfo], allowed_ids: set[int] | None) -> None:
        super().__init__(root)
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
        self._users: dict[str, list[tuple[int, str]]] = {}

        self.close_button = QPushButton(S.EFFECTS_CLOSE)
        self.close_button.setIcon(icon("x"))
        self.close_button.clicked.connect(self.close_requested)
        self.memory_bar = QProgressBar()
        self.memory_bar.setObjectName("effectsMemory")
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setTextVisible(False)  # the figures are their own label: text over a thin bar cannot be read
        self.memory_label = QLabel(S.NOT_AVAILABLE)
        self.memory_label.setProperty("role", "value")
        self.message_label = QLabel("")
        self.message_label.setProperty("role", "offline")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry_button = QPushButton(S.EFFECTS_RETRY)
        self.retry_button.clicked.connect(self.refresh_requested)
        self.search = QLineEdit()
        self.search.setPlaceholderText(S.SEARCH_EFFECTS)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(S.EFFECTS_SEARCH_TIP)
        self.search.addAction(icon("search", "text-secondary", 17), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _text: self._populate())

        self.installed_list, self.installed_count, self.installed_empty = _CardList(), QLabel(""), QLabel("")
        self.available_list, self.available_count, self.available_empty = _CardList(), QLabel(""), QLabel("")
        self.installed_list.itemSelectionChanged.connect(lambda: self._on_selection(self.installed_list))
        self.available_list.itemSelectionChanged.connect(lambda: self._on_selection(self.available_list))

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
        self.install_button.clicked.connect(self._on_install)
        self.remove_button.clicked.connect(self._on_remove)

        title = QHBoxLayout()
        title.addWidget(SectionLabel(S.EFFECTS_TITLE))
        title.addStretch(1)
        title.addWidget(self.close_button)
        memory = QHBoxLayout()
        memory.setSpacing(12)
        memory.addWidget(QLabel(S.MEMORY_LABEL))
        memory.addWidget(self.memory_bar, stretch=1)
        memory.addWidget(self.memory_label)

        self.content = QWidget()
        content = QHBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        lists = QVBoxLayout()
        lists.addWidget(self.search)
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
        dl.addWidget(self.reason_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.remove_button)
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
        return [cards.item(i).data(ROLE_ENTRY).file for i in range(cards.count())]

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

    def set_state(self, flst_bytes: bytes, files: list[str], usage) -> None:
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
        self.message_box.hide()
        self.content.show()
        self._populate()
        self.state_shown.emit()

    def set_patch_usage(self, complete: bool, unsaved: bool, users: dict[str, list[tuple[int, str]]]) -> None:
        """What the editor knows: every patch read, any unsaved edit, and the patches (number, name) using each file."""
        self._patches_complete, self._unsaved, self._users = complete, unsaved, users
        self._update_actions()

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self._busy_text = text
        self.search.setEnabled(not busy)
        self.close_button.setEnabled(not busy)
        self.installed_list.setEnabled(not busy)
        self.available_list.setEnabled(not busy)
        self._update_actions()

    # ------------------------------------------------------------ lists and selection

    def _matches(self, entry: Entry, query: str) -> bool:
        haystack = f"{entry.name} {entry.file} {entry.group} {S.group_label(entry.group)}".lower()
        return all(word in haystack for word in query.lower().split())

    def _populate(self) -> None:
        query = self.search.text().strip()
        for cards, entries, count, empty, none_text in (
                (self.installed_list, self._installed, self.installed_count, self.installed_empty,
                 S.EFFECTS_NONE_INSTALLED),
                (self.available_list, self._available, self.available_count, self.available_empty,
                 S.EFFECTS_NONE_AVAILABLE)):
            shown = [e for e in entries if self._matches(e, query)]
            cards.blockSignals(True)
            cards.clear()
            for entry in shown:
                item = QListWidgetItem()
                item.setData(ROLE_ENTRY, entry)
                cards.addItem(item)
                if entry.file == self._selected:
                    cards.setCurrentItem(item)
            cards.blockSignals(False)
            count.setText(S.effects_count(len(shown), len(entries)))
            empty.setText(none_text)
            empty.setVisible(not shown)
        if self._entry(self._selected) is None:
            self._selected = None
        self._show_detail()

    def select_effect(self, file: str) -> None:
        """Select the card of ``file`` in whichever list shows it."""
        for cards in (self.installed_list, self.available_list):
            for i in range(cards.count()):
                if cards.item(i).data(ROLE_ENTRY).file == file:
                    cards.setCurrentRow(i)
                    return

    def _on_selection(self, cards: QListWidget) -> None:
        item = cards.currentItem() if cards.selectedItems() else None
        if item is None:
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

    # ------------------------------------------------------------ actions

    def _update_actions(self) -> None:
        entry = self._entry(self._selected)
        installing = entry is not None and any(e.file == entry.file for e in self._available)
        removing = entry is not None and not installing
        self.install_button.setVisible(installing)
        self.remove_button.setVisible(removing)
        enabled, reason, blocking = False, "", False
        if entry is None or not self._loaded:
            pass
        elif self._busy:
            reason = self._busy_text
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
            elif not self._patches_complete:
                reason = S.EFFECTS_PATCHES_INCOMPLETE
            elif self._unsaved:
                reason = S.EFFECTS_UNSAVED_PATCHES
            elif self._users.get(entry.file):
                reason = S.effects_in_use(self._users[entry.file])
            else:
                enabled, reason = True, S.EFFECTS_REMOVE_OK
            blocking = not enabled
        self.install_button.setEnabled(enabled and installing)
        self.remove_button.setEnabled(enabled and removing)
        self.reason_label.setText(reason)
        self.reason_label.setProperty("blocking", blocking)
        self.reason_label.style().unpolish(self.reason_label)
        self.reason_label.style().polish(self.reason_label)
        tip = reason if reason else ""
        self.install_button.setToolTip(tip)
        self.remove_button.setToolTip(tip)

    def _on_install(self) -> None:
        entry = self._entry(self._selected)
        if entry is None or entry.path is None or entry.size is None or not self.install_button.isEnabled():
            return
        if ConfirmDialog.ask(self, S.effects_confirm_install_title(entry.name),
                             S.effects_confirm_install(entry.name, entry.file, entry.size, self._free or 0),
                             S.EFFECTS_INSTALL):
            self.install_requested.emit(entry.file, entry.path)

    def _on_remove(self) -> None:
        entry = self._entry(self._selected)
        if entry is None or not self.remove_button.isEnabled():
            return
        if ConfirmDialog.ask(self, S.effects_confirm_remove_title(entry.name),
                             S.effects_confirm_remove(entry.name, entry.file), S.EFFECTS_REMOVE, danger=True):
            self.remove_requested.emit(entry.file)
