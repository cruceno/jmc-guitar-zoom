"""The "Banco de patches" screen and the window-side operations behind it.

The screen only shows and asks (two card lists, a search field, two buttons, a preview line and drag and
drop); ``BankMixin`` decides and writes. A patch moves, it is never copied: it lives either on the pedal or
in the bank. The order of every operation is the safety net: the patch that leaves the pedal is stored in
the bank (file written and read back) before anything is written to the pedal, and a bank entry is removed
only after the pedal's read-back matched what was sent. Pedal writes go through ``PedalWorker.write_patches``
(autosave backup, write, read-back compare, stop at the first failure).
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QByteArray, QMimeData, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from zoomstudio.patches import bank as bank_module
from zoomstudio.patches import edit, library
from zoomstudio.patches.bank import BankError, PatchBank
from zoomstudio.patches.model import Patch
from zoomstudio.patches.zptc import build_zptc, parse_zptc

from . import strings as S
from . import tokens
from .cards import (
    ROLE_DIRTY, ROLE_DROP, ROLE_META, ROLE_NAME, ROLE_NUMBER, ROLE_STRIP, BankCardDelegate, PatchCardDelegate,
    with_alpha,
)
from .dialogs import ConfirmDialog
from .glass import BackdropRoot, GlassPanel
from .icons import icon
from .painted import SectionLabel
from .widgets import MIME_PATCH, PatchList

MIME_BANK = "application/x-zoomstudio-bank-entry"  # payload: bank entry id (UTF-8 text)
ROLE_ENTRY_ID = Qt.ItemDataRole.UserRole + 40


class PositionList(PatchList):
    """The pedal's positions as patch cards. A bank card dropped on one asks to load it there."""

    bank_dropped = Signal(str, int)  # bank entry id, location

    def __init__(self) -> None:
        super().__init__()
        self.drop_row: int | None = None
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def show_drop_target(self, row: int | None) -> None:
        """Highlight the card of ``row`` (None: no highlight)."""
        if row == self.drop_row:
            return
        for old in (self.drop_row, row):
            item = self.item(old) if old is not None and 0 <= old < self.count() else None
            if item is not None:
                item.setData(ROLE_DROP, old == row)
        self.drop_row = row
        self.viewport().update()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasFormat(MIME_BANK):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        item = self.itemAt(event.position().toPoint())
        if event.mimeData().hasFormat(MIME_BANK) and item is not None:
            self.show_drop_target(self.row(item))
            event.acceptProposedAction()
        else:
            self.show_drop_target(None)
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.show_drop_target(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt API)
        item = self.itemAt(event.position().toPoint())
        self.show_drop_target(None)
        if not event.mimeData().hasFormat(MIME_BANK) or item is None:
            event.ignore()  # a position dropped on a position is the editor's swap, not a bank operation
            return
        entry_id = bytes(event.mimeData().data(MIME_BANK)).decode()
        event.acceptProposedAction()
        self.bank_dropped.emit(entry_id, int(item.data(Qt.ItemDataRole.UserRole)))


class BankList(QListWidget):
    """The bank's cards. A position dropped anywhere on the list asks to stash it."""

    position_dropped = Signal(int)  # location of the patch to keep

    def __init__(self) -> None:
        super().__init__()
        self._dropping = False
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.IgnoreAction)
        self.setItemDelegate(BankCardDelegate(self))
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)

    @property
    def dropping(self) -> bool:
        return self._dropping

    def show_drop_target(self, on: bool) -> None:
        if on != self._dropping:
            self._dropping = on
            self.viewport().update()

    def mimeData(self, items) -> QMimeData:  # noqa: N802 (Qt API)
        mime = QMimeData()
        if items:
            mime.setData(MIME_BANK, QByteArray(str(items[0].data(ROLE_ENTRY_ID)).encode()))
        return mime

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasFormat(MIME_PATCH):
            self.show_drop_target(True)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasFormat(MIME_PATCH):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.show_drop_target(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.show_drop_target(False)
        if not event.mimeData().hasFormat(MIME_PATCH):
            event.ignore()
            return
        try:
            location = int(bytes(event.mimeData().data(MIME_PATCH)).decode())
        except (ValueError, UnicodeDecodeError):  # not one of our patch drags
            event.ignore()
            return
        event.acceptProposedAction()
        self.position_dropped.emit(location)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)
        if self._dropping:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            accent = tokens.color("accent")
            fill = with_alpha(accent, 0.10)
            rect = self.viewport().rect().adjusted(3, 3, -3, -3)
            p.setBrush(fill)
            p.setPen(QPen(accent, 2.5, Qt.PenStyle.DashLine))
            p.drawRoundedRect(rect, 12, 12)
            p.setPen(accent)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, S.BANK_DROP_HERE)
            p.end()


class BankScreen(GlassPanel):
    """Pedal positions on the left, the bank on the right, and the two actions between a pick and a pick."""

    close_requested = Signal()
    stash_requested = Signal(int)  # location whose patch goes to the bank
    load_requested = Signal(str, int)  # bank entry id, location to load it into
    state_shown = Signal()

    def __init__(self, root: BackdropRoot) -> None:
        super().__init__(root)
        self._can_act = False
        self._busy = False
        self._connected = False
        self._rows: dict[int, tuple[int, str, bool]] = {}  # location -> (display, name or "" when free, dirty)
        self._entries: list[dict] = []

        self.close_button = QPushButton(S.BANK_CLOSE)
        self.close_button.setIcon(icon("x"))
        self.close_button.clicked.connect(self.close_requested)
        self.positions = PositionList()
        self.positions.setItemDelegate(PatchCardDelegate(self.positions))
        self.positions.setAccessibleName(S.BANK_POSITIONS_LIST)
        self.positions.itemSelectionChanged.connect(self._update_actions)
        self.positions.bank_dropped.connect(self.load_requested)
        self.bank_list = BankList()
        self.bank_list.setAccessibleName(S.BANK_ENTRIES_LIST)
        self.bank_list.itemSelectionChanged.connect(self._update_actions)
        self.bank_list.position_dropped.connect(self.stash_requested)
        self.search = QLineEdit()
        self.search.setPlaceholderText(S.BANK_SEARCH)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(S.BANK_SEARCH_TIP)
        self.search.addAction(icon("search", "text-secondary", 17), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _text: self._populate_entries())
        self.positions_caption = QLabel("")
        self.positions_caption.setProperty("role", "secondary")
        self.bank_caption = QLabel("")
        self.bank_caption.setProperty("role", "secondary")
        self.empty_label = QLabel("")
        self.empty_label.setProperty("role", "offline")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label = QLabel(S.BANK_HINT)
        self.preview_label.setProperty("role", "secondary")
        self.preview_label.setWordWrap(True)
        self.note_label = QLabel("")
        self.note_label.setProperty("role", "reason")
        self.note_label.setWordWrap(True)
        self.load_button = QPushButton(S.BANK_LOAD)
        self.load_button.setProperty("primary", True)
        self.load_button.setIcon(icon("arrowUp", "on-accent"))
        self.load_button.setToolTip(S.BANK_LOAD_TIP)
        self.load_button.clicked.connect(self._on_load_clicked)
        self.stash_button = QPushButton(S.BANK_STASH)
        self.stash_button.setIcon(icon("bank"))
        self.stash_button.setToolTip(S.BANK_STASH_TIP)
        self.stash_button.clicked.connect(self._on_stash_clicked)

        title = QHBoxLayout()
        title.addWidget(SectionLabel(S.BANK_TITLE))
        title.addStretch(1)
        title.addWidget(self.close_button)
        left = QVBoxLayout()
        left.addLayout(self._header(S.BANK_POSITIONS, self.positions_caption))
        left.addWidget(self.positions, stretch=1)
        right = QVBoxLayout()
        right.addLayout(self._header(S.BANK_ENTRIES, self.bank_caption))
        right.addWidget(self.search)
        stack = QWidget()
        stack_layout = QVBoxLayout(stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.addWidget(self.bank_list, stretch=1)
        stack_layout.addWidget(self.empty_label)
        right.addWidget(stack, stretch=1)
        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addLayout(left, stretch=1)
        columns.addLayout(right, stretch=1)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.note_label, stretch=1)
        buttons.addWidget(self.stash_button)
        buttons.addWidget(self.load_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        layout.addLayout(title)
        layout.addLayout(columns, stretch=1)
        layout.addWidget(self.preview_label)
        layout.addLayout(buttons)
        self._update_actions()

    @staticmethod
    def _header(title: str, caption: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(SectionLabel(title))
        row.addStretch(1)
        row.addWidget(caption)
        return row

    # ------------------------------------------------------------------ data in

    def set_positions(self, rows: list[tuple[int, int, str, object, bool]]) -> None:
        """``rows`` = (location, display number, name or "" when free, chain strip, unsaved edits)."""
        if self.positions.count() != len(rows):
            self.positions.clear()
            for location, *_rest in rows:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, location)
                self.positions.addItem(item)
        for item, (location, display, name, strip, dirty) in zip(
                (self.positions.item(i) for i in range(self.positions.count())), rows):
            item.setData(Qt.ItemDataRole.UserRole, location)
            item.setData(ROLE_NUMBER, display)
            item.setData(ROLE_NAME, name)
            item.setData(ROLE_STRIP, strip if name else None)
            item.setData(ROLE_DIRTY, dirty)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{display}, {name or S.EMPTY}")
        self._rows = {loc: (display, name, dirty) for loc, display, name, _s, dirty in rows}
        occupied = sum(1 for _l, _d, name, _s, _x in rows if name)
        self.positions_caption.setText(f"{occupied}/{len(rows)}")
        self._update_actions()

    def set_entries(self, entries: list[dict]) -> None:
        """``entries`` = dicts with id, name, meta, strip (the window builds them from the bank)."""
        self._entries = entries
        self._populate_entries()

    def _populate_entries(self) -> None:
        keep = self.selected_entry()
        needle = self.search.text().strip().lower()
        self.bank_list.blockSignals(True)
        self.bank_list.clear()
        shown = 0
        for entry in self._entries:
            if needle and needle not in f"{entry['name']} {entry['meta']}".lower():
                continue
            item = QListWidgetItem()
            item.setData(ROLE_ENTRY_ID, entry["id"])
            item.setData(ROLE_NAME, entry["name"])
            item.setData(ROLE_META, entry["meta"])
            item.setData(ROLE_STRIP, entry["strip"])
            item.setData(Qt.ItemDataRole.AccessibleTextRole, entry["accessible"])
            self.bank_list.addItem(item)
            if entry["id"] == keep:
                self.bank_list.setCurrentItem(item)
            shown += 1
        self.bank_list.blockSignals(False)
        self.bank_caption.setText(S.bank_count(len(self._entries)))
        self.empty_label.setText("" if shown else (S.BANK_NO_MATCH if self._entries else S.BANK_EMPTY))
        self.empty_label.setVisible(not shown)
        self._update_actions()
        self.state_shown.emit()

    def set_context(self, connected: bool, complete: bool, busy: bool) -> None:
        """What the window allows right now: both actions need a connected pedal, every patch read, no write running."""
        self._connected, self._busy = connected, busy
        self._can_act = connected and complete and not busy
        self._update_actions()

    # ------------------------------------------------------------------ data out

    def entry_names(self) -> list[str]:
        return [self.bank_list.item(i).data(ROLE_NAME) for i in range(self.bank_list.count())]

    def selected_position(self) -> int | None:
        item = self.positions.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None and item.isSelected() else None

    def selected_entry(self) -> str | None:
        item = self.bank_list.currentItem()
        return str(item.data(ROLE_ENTRY_ID)) if item is not None and item.isSelected() else None

    def select_position(self, location: int | None) -> None:
        if location is None or not 1 <= location <= self.positions.count():
            self.positions.clearSelection()
            self.positions.setCurrentRow(-1)
            return
        self.positions.setCurrentRow(location - 1)
        self.positions.scrollToItem(self.positions.item(location - 1))

    def select_entry(self, entry_id: str | None) -> None:
        for i in range(self.bank_list.count()):
            if self.bank_list.item(i).data(ROLE_ENTRY_ID) == entry_id:
                self.bank_list.setCurrentRow(i)
                return
        self.bank_list.clearSelection()
        self.bank_list.setCurrentRow(-1)

    def choose_position(self, current: int | None) -> int | None:
        """Ask for the position to load into (the selected one is the default); None when cancelled."""
        labels = [f"{display} · {name or S.EMPTY}" for _loc, (display, name, _d) in sorted(self._rows.items())]
        locations = sorted(self._rows)
        start = locations.index(current) if current in locations else 0
        label, ok = QInputDialog.getItem(self, S.BANK_CHOOSE_TITLE, S.BANK_CHOOSE_LABEL, labels, start, False)
        return locations[labels.index(label)] if ok and label in labels else None

    # ------------------------------------------------------------------ actions

    def _on_stash_clicked(self) -> None:
        location = self.selected_position()
        if location is not None:
            self.stash_requested.emit(location)

    def _on_load_clicked(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        location = self.choose_position(self.selected_position())
        if location is not None:
            self.load_requested.emit(entry, location)

    def _update_actions(self) -> None:
        location, entry = self.selected_position(), self.selected_entry()
        self.stash_button.setEnabled(self._can_act and location is not None)
        self.load_button.setEnabled(self._can_act and entry is not None)
        self.note_label.setText(S.BANK_BUSY_NOTE if self._busy else ("" if self._connected else S.BANK_OFFLINE_NOTE))
        position = None
        dirty = False
        if location is not None and location in self._rows:
            display, name, dirty = self._rows[location]
            position = (display, name or None)
        entry_name = next((e["name"] for e in self._entries if e["id"] == entry), None) if entry else None
        self.preview_label.setText(S.bank_preview(position, entry_name, dirty))


class BankMixin:
    """Mixed into ``MainWindow``: the bank store, the two operations and the screen's refresh."""

    def _init_bank(self, bank_dir) -> None:
        self._bank_dir = bank_dir
        self._bank_store: PatchBank | None = None
        self._bank_op: dict | None = None
        self._bank_strips: dict[str, object] = {}
        self._bank_open = False

    @property
    def bank_store(self) -> PatchBank:
        if self._bank_store is None:
            folder = self._bank_dir
            if folder is None and self.library_dir is not None:
                folder = self.library_dir / "bank"
            self._bank_store = PatchBank(folder if folder is not None else bank_module.default_dir())
        return self._bank_store

    # ------------------------------------------------------------------ screen

    def open_bank_screen(self) -> None:
        if self.bank_button.isEnabled():
            self.bank_button.setChecked(True)

    def _on_bank_toggled(self, on: bool) -> None:
        self._bank_open = on
        self.splitter.setEnabled(not on)
        self.splitter.setVisible(not on)
        self.bank_panel.setVisible(on)
        self.edit_button.setEnabled(not on)
        self.library_button.setEnabled(not on)
        self._update_buttons()
        if on:
            self._refresh_bank_screen()

    def _refresh_bank_screen(self) -> None:
        """Both lists from the current patches and the bank folder (cheap: 50 rows and a few entries)."""
        if not self._bank_open:
            return
        rows = []
        for location in range(1, self._patch_count + 1):
            patch = self._patches.get(location)
            free = patch is None or self._is_free(patch)
            rows.append((location, self._display(location), "" if free else (patch.name or S.UNNAMED),
                         None if free else self._chain_strip(patch), self.is_dirty(location)))
        self.bank_panel.set_positions(rows)
        entries = []
        for entry in reversed(self.bank_store.list()):  # newest first
            key = f"{entry.id}:{entry.sha256}"
            if key not in self._bank_strips:
                try:
                    self._bank_strips[key] = self._chain_strip(parse_zptc(self.bank_store.read(entry.id)))
                except (BankError, ValueError):
                    self._bank_strips[key] = None
            meta = f"{S.bank_origin(entry.origin)} · {S.bank_date(entry.stored_at)}"
            entries.append({"id": entry.id, "name": entry.name or S.UNNAMED,
                            "meta": meta if self._bank_strips[key] is not None else f"{meta} · {S.BANK_DAMAGED}",
                            "strip": self._bank_strips[key],
                            "accessible": S.bank_card_name(entry.name, entry.origin, entry.stored_at)})
        self.bank_panel.set_entries(entries)
        self._refresh_bank_context()

    def _refresh_bank_context(self) -> None:
        self.bank_panel.set_context(self._can_write, self._patches_complete, self._saving)

    # ------------------------------------------------------------------ gates

    @staticmethod
    def _is_free(patch: Patch) -> bool:
        """A position with no effect in its chain: what the pedal shows as Empty."""
        return all(slot.is_placeholder for slot in patch.effects)

    def _bank_gate(self, location: int) -> bool:
        """Report and refuse unless the pedal is connected, fully read, idle, and the position has no unsaved edits."""
        if self._saving or self._bank_op is not None:
            return False
        if not self._can_write:
            self._report_error(S.ERR_BANK_OFFLINE)
            return False
        if not self._patches_complete:
            self._report_error(S.ERR_BANK_LOADING)
            return False
        if self.is_dirty(location):
            self._report_error(S.err_bank_unsaved(self._display(location)))
            return False
        if self.backup_dir is None:
            self._report_error(S.ERR_NO_BACKUP_DIR)
            return False
        return True

    # ------------------------------------------------------------------ operations

    def stash_from_menu(self, location: int) -> None:
        """The patch list's context menu: show the bank screen on that position and ask."""
        self.open_bank_screen()
        if self._bank_open:
            self.bank_panel.select_position(location)
        self.stash_position(location)

    def stash_position(self, location: int) -> None:
        """Keep the pedal's patch in the bank, then free the position (write the factory Empty)."""
        if not self._bank_gate(location):
            return
        patch = self._patches.get(location)
        if patch is None or self._is_free(patch):
            self._report_error(S.ERR_BANK_NOTHING_TO_KEEP)
            return
        display = self._display(location)
        if not ConfirmDialog.ask(self, S.BANK_STASH_TITLE, S.ask_bank_stash(display, patch.name), S.CONFIRM_BANK_STASH):
            return
        try:
            entry = self.bank_store.add(build_zptc(patch), origin=display)
        except (BankError, ValueError) as exc:
            self._report_error(S.err_bank_store(exc))
            return
        self._bank_op = {"kind": "stash", "location": location, "name": patch.name, "entry": entry.id}
        if not self._queue_write({location: library.empty_patch()}):
            self._bank_op = None
        self._refresh_bank_screen()

    def load_from_bank(self, entry_id: str, location: int) -> None:
        """Write a bank patch to ``location``; an occupant goes to the bank first and the entry leaves it last."""
        if not self._bank_gate(location):
            return
        try:
            entry = self.bank_store.get(entry_id)
            incoming = parse_zptc(self.bank_store.read(entry_id))
        except (BankError, ValueError) as exc:
            self._report_error(S.err_bank_unknown(exc))
            return
        incoming = edit.with_fillers(incoming, self.catalog)
        blocked = self._blockers({location: incoming})
        if blocked:
            self._report_error(S.err_nothing_written_fix(self._describe_blockers(blocked)))
            return
        current = self._patches.get(location)
        occupant = None if current is None or self._is_free(current) else copy.deepcopy(current)
        display = self._display(location)
        if not ConfirmDialog.ask(self, S.BANK_LOAD_TITLE,
                                 S.ask_bank_load(display, entry.name, None if occupant is None else occupant.name),
                                 S.CONFIRM_BANK_LOAD):
            return
        stored = None
        if occupant is not None:
            try:
                stored = self.bank_store.add(build_zptc(occupant), origin=display)
            except (BankError, ValueError) as exc:
                self._report_error(S.err_bank_store(exc))
                return
        self._bank_op = {"kind": "load", "location": location, "name": entry.name, "entry": entry_id,
                         "occupant": None if occupant is None else occupant.name, "stored": stored is not None}
        if not self._queue_write({location: incoming}):
            self._bank_op = None
        self._refresh_bank_screen()

    def _bank_queue_done(self, written: object, failed: int) -> None:
        """The write queue ended: finish the bank operation that started it (if any) and refresh the lists."""
        op, self._bank_op = self._bank_op, None
        if op is None:
            self._refresh_bank_screen()
            return
        location = op["location"]
        ok = not failed and location in written
        display = self._display(location)
        if op["kind"] == "stash":
            if ok:
                self.statusBar().showMessage(S.bank_stashed(display, op["name"]))
            else:
                self._report_error(S.ERR_BANK_NOT_FREED)
        else:
            if ok:
                try:
                    self.bank_store.remove(op["entry"])
                except BankError as exc:
                    ok = False
                    self._report_error(S.err_bank_not_removed(op["name"], exc))
                else:
                    self.statusBar().showMessage(S.bank_loaded(display, op["name"], op["occupant"]))
            else:
                self._report_error(S.ERR_BANK_KEPT_BOTH if op["stored"] else S.ERR_BANK_KEPT_ONE)
        self._refresh_bank_screen()
        self.bank_finished.emit(op["kind"], ok)
