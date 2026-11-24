"""Main window: patch list | signal chain + parameters | effect catalog, with undoable editing."""

from __future__ import annotations

import copy
import re
from pathlib import Path

from PySide6.QtCore import QMetaObject, QRegularExpression, QThread, Qt, Signal, Slot
from PySide6.QtGui import (
    QAction, QBrush, QColor, QKeySequence, QRegularExpressionValidator, QUndoCommand, QUndoGroup, QUndoStack,
)
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.patches import edit
from zoomstudio.patches.model import NAME_MAX_LEN, VOLUME_MAX, Patch
from zoomstudio.patches.zptc import build_zptc, parse_zptc

from .library import LibraryMixin
from .widgets import CatalogPanel, ChainView, EffectTile, ParamPanel, ParamRow, PatchList
from .worker import PedalWorker, TransportFactory

DEFAULT_PATCH_COUNT = 50
DISPLAY_OFFSET = 9  # the pedal shows locations 1..50 as 10..59
MODEL_NAMES = {0x6E: "A1 FOUR"}
_PATCH_FILE = re.compile(r"^(\d+)\.zptc$", re.IGNORECASE)
_EMPTY_COLOR = QColor("#6c6f75")
_MERGE_ID = 1


def live_message(patch: Patch, slot_index: int, param_index: int | None, value: int) -> tuple[int, int, int]:
    """Map an edit to the arguments of ``PedalClient.set_param(slot, param, value)``.

    ``param_index`` is the dial index of the effect (0-based) or ``None`` for on/off. Readme of the
    protocol: param 0 = on/off, 2-9 = dials.

    Verified on a real A1 FOUR (fw 1.01, 2026-11-24): the pedal's ``slot`` is the index into the
    chain *with* the ``0x00000001`` wide fillers (what ``patch.effects`` holds) and ``param`` is the
    dial index + 2. FD DLXR Bass (slot 1, param 3), Hall PreD after two wide effects (slot 6,
    param 2) and Gt GEQ 7 VOL (slot 4, param 9) each changed exactly that value on the pedal.
    """
    slot = slot_index
    if param_index is None:
        return slot, 0, value
    return slot, param_index + 2, value


class PatchEdit(QUndoCommand):
    """Replace a location's patch by a snapshot; undo restores the previous one.

    Consecutive edits with the same ``key`` (a dial drag, typing a name) merge into one step.
    """

    def __init__(self, window: "MainWindow", location: int, before: Patch | None, after: Patch | None,
                 text: str, key: tuple | None, sel_before: int | None, sel_after: int | None) -> None:
        super().__init__(text)
        self._window = window
        self.location = location
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.key = key
        self.sel_before = sel_before
        self.sel_after = sel_after

    def id(self) -> int:
        return _MERGE_ID if self.key is not None else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 (Qt API)
        if (not isinstance(other, PatchEdit) or other.key != self.key or other.location != self.location):
            return False
        self.after = other.after
        self.sel_after = other.sel_after
        return True

    def redo(self) -> None:
        self._window._store(self.location, self.after, self.sel_after)

    def undo(self) -> None:
        self._window._store(self.location, self.before, self.sel_before)


class MainWindow(LibraryMixin, QMainWindow):
    patches_loaded = Signal()  # a full read (pedal) or folder load finished
    error_shown = Signal(str)
    save_finished = Signal(bool)  # a SAVE to the pedal ended (True: verified by read-back)
    _save_requested = Signal(int, object, object)
    _param_requested = Signal(int, int, int)
    _select_requested = Signal(int)
    backup_finished = Signal(str, bool)  # backup-all ended: patches folder ("" if none), success
    queue_finished = Signal(object, int)  # a multi-slot write ended: locations written, failed location
    _backup_requested = Signal(object, bool, object)
    _queue_requested = Signal(object, object)

    def __init__(self, catalog: dict[int, EffectInfo], a1_ids: set[int] | None = None,
                 transport_factory: TransportFactory | None = None, installed_label: str = "pedal",
                 pedal_timeout: float = 3.0, backup_dir: Path | None = None,
                 library_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Zoom Studio")
        self.resize(1400, 780)
        self.catalog = catalog
        self.allowed_ids = a1_ids  # effects that run on the A1 FOUR (None: no restriction)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else None
        self.library_dir = Path(library_dir) if library_dir is not None else None  # parent of backup-* folders
        self._init_library()
        self._patches: dict[int, Patch] = {}
        self._stacks: dict[int, QUndoStack] = {}
        self.undo_group = QUndoGroup(self)
        self._suppress_refresh = False
        self._saving = False
        self._live_location: int | None = None
        self._patch_count = DEFAULT_PATCH_COUNT
        self._location: int | None = None
        self._offline_dir: Path | None = None
        self._is_connected = False
        self._closed = False
        self._worker: PedalWorker | None = None
        self._thread: QThread | None = None

        self._build_ui(a1_ids, installed_label)
        self._rebuild_patch_list()
        if transport_factory is not None:
            self._start_worker(transport_factory, pedal_timeout)
        self._update_buttons()

    # ---------------------------------------------------------------- UI

    def _build_ui(self, a1_ids: set[int] | None, installed_label: str) -> None:
        header = QFrame()
        header.setFrameShape(QFrame.Shape.StyledPanel)
        h = QHBoxLayout(header)
        self.connection_label = QLabel("Not connected")
        self.connection_label.setMinimumWidth(260)
        self.memory_bar = QProgressBar()
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setValue(0)
        self.memory_bar.setFormat("Memory: n/a")
        self.memory_bar.setMinimumWidth(240)
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        self.open_button = QPushButton("Open folder...")
        self.reload_button = QPushButton("Reload")
        self.open_file_button = QPushButton("Open file...")
        self.save_file_button = QPushButton("Save as file...")
        self.save_button = QPushButton("Save to pedal")
        self.live_check = QCheckBox("Live")
        self.live_check.setToolTip("Also send parameter and on/off changes to the pedal while editing "
                                   "(experimental: slot numbering is not verified on hardware)")
        h.addWidget(self.connection_label)
        h.addWidget(self.memory_bar)
        h.addStretch(1)
        for w in (self.live_check, self.open_file_button, self.save_file_button, self.save_button,
                  self.connect_button, self.disconnect_button, self.open_button, self.reload_button):
            h.addWidget(w)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.disconnect_button.clicked.connect(self._on_disconnect_clicked)
        self.open_button.clicked.connect(self._choose_folder)
        self.reload_button.clicked.connect(self.reload)
        self.save_button.clicked.connect(self.save_current_patch)
        self.save_file_button.clicked.connect(self._choose_save_file)
        self.open_file_button.clicked.connect(self._choose_open_file)
        self.live_check.toggled.connect(self._on_live_toggled)

        self.undo_action = self.undo_group.createUndoAction(self, "Undo")
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.redo_action = self.undo_group.createRedoAction(self, "Redo")
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        self.patch_list = PatchList()
        self.patch_list.currentRowChanged.connect(self._on_row_changed)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Patches"))
        lv.addWidget(self.patch_list)
        self.patch_panel = left

        self.patch_title = QLabel("No patch selected")
        self.patch_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(NAME_MAX_LEN)
        self.name_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"[ -~]*")))
        self.name_edit.setFixedWidth(130)
        self.name_edit.setToolTip(f"Patch name: up to {NAME_MAX_LEN} printable ASCII characters")
        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(0, VOLUME_MAX)
        self.volume_spin.setToolTip("Patch volume")
        self.dsp_bar = QProgressBar()
        self.dsp_bar.setRange(0, 100)
        self.dsp_bar.setFormat("DSP: n/a")
        self.dsp_bar.setMinimumWidth(180)
        undo_button, redo_button = QToolButton(), QToolButton()
        undo_button.setDefaultAction(self.undo_action)
        redo_button.setDefaultAction(self.redo_action)
        self.editor_row = QWidget()
        er = QHBoxLayout(self.editor_row)
        er.setContentsMargins(0, 0, 0, 0)
        for widget in (QLabel("Name"), self.name_edit, QLabel("Volume"), self.volume_spin, self.dsp_bar,
                       undo_button, redo_button):
            er.addWidget(widget)
        er.addStretch(1)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.volume_spin.valueChanged.connect(self._on_volume_changed)

        self.chain = ChainView()
        self.params = ParamPanel()
        centre = QWidget()
        cv = QVBoxLayout(centre)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(self.patch_title)
        cv.addWidget(self.editor_row)
        cv.addWidget(self.chain)
        cv.addWidget(self.params, stretch=1)
        self.centre = centre
        self.chain.tile_selected.connect(self._on_tile_selected)
        self.chain.power_toggled.connect(self._on_power_toggled)
        self.chain.remove_requested.connect(self.remove_effect)
        self.chain.effect_dropped.connect(self.replace_effect)
        self.chain.tile_moved.connect(self.move_effect)
        self.params.param_changed.connect(self._on_param_changed)

        self.catalog_panel = CatalogPanel(self.catalog, a1_ids, installed_label)
        self.catalog_panel.effect_activated.connect(self._on_catalog_activated)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(centre)
        splitter.addWidget(self.catalog_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([260, 760, 360])

        root = QWidget()
        rv = QVBoxLayout(root)
        rv.addWidget(header)
        rv.addWidget(splitter, stretch=1)
        self.setCentralWidget(root)
        self._build_library_ui()
        self.statusBar().showMessage("Ready")

    def _update_buttons(self) -> None:
        can_connect = self._worker is not None
        self.connect_button.setEnabled(can_connect and not self._is_connected)
        self.disconnect_button.setEnabled(self._is_connected)
        self.reload_button.setEnabled(self._is_connected or self._offline_dir is not None)
        patch = self.current_patch
        self.open_file_button.setEnabled(self._location is not None and not self._saving)
        self.save_file_button.setEnabled(patch is not None)
        self.live_check.setEnabled(self._is_connected)
        blockers = self.save_blockers()
        dirty = self._location is not None and self.is_dirty(self._location)
        self.save_button.setEnabled(
            self._is_connected and patch is not None and dirty and not blockers and not self._saving)
        if blockers:
            tip = "Cannot save: " + "; ".join(blockers[:3])
        elif not self._is_connected:
            tip = "Connect to the pedal to save"
        elif not dirty:
            tip = "No unsaved edits in this patch"
        else:
            tip = "Back up the slot, write this patch to the pedal and verify it by reading it back"
        self.save_button.setToolTip(tip)
        self._update_library_actions()

    # ------------------------------------------------------------- patches

    def _display(self, location: int) -> int:
        return location + DISPLAY_OFFSET

    def _rebuild_patch_list(self) -> None:
        self.patch_list.blockSignals(True)
        self.patch_list.clear()
        for loc in range(1, self._patch_count + 1):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, loc)
            self.patch_list.addItem(item)
            self._refresh_item(loc)
        self.patch_list.setCurrentRow(-1)
        self.patch_list.blockSignals(False)
        self._location = None
        self.undo_group.setActiveStack(None)
        self.chain.clear()
        self.params.clear()
        self.patch_title.setText("No patch selected")
        self._update_header()

    def is_empty_slot(self, location: int) -> bool:
        return location not in self._patches

    def is_dirty(self, location: int) -> bool:
        stack = self._stacks.get(location)
        try:
            return stack is not None and not stack.isClean()
        except RuntimeError:  # the stack's C++ object is gone (window being destroyed)
            return False

    def any_dirty(self) -> bool:
        return any(self.is_dirty(loc) for loc in self._stacks)

    @property
    def current_patch(self) -> Patch | None:
        return self._patches.get(self._location) if self._location is not None else None

    @property
    def current_location(self) -> int | None:
        return self._location

    def _refresh_item(self, location: int) -> None:
        if not 1 <= location <= self.patch_list.count():
            return
        item = self.patch_list.item(location - 1)
        patch = self._patches.get(location)
        number = f"{self._display(location):>2}"
        if patch is None:
            item.setText(f"{number}  -")
            item.setForeground(QBrush(_EMPTY_COLOR))
        else:
            name = patch.name or "(unnamed)"
            item.setText(f"{number}  {name}{' *' if self.is_dirty(location) else ''}")
            item.setForeground(QBrush(self.palette().text().color()))

    def _stack(self, location: int) -> QUndoStack:
        stack = self._stacks.get(location)
        if stack is None:
            stack = QUndoStack(self.undo_group)
            stack.cleanChanged.connect(lambda _clean, loc=location: self._on_clean_changed(loc))
            self._stacks[location] = stack
        return stack

    def _on_clean_changed(self, location: int) -> None:
        try:
            self._refresh_item(location)
            self._update_buttons()
        except RuntimeError:  # window being destroyed
            pass

    def _reset_edits(self) -> None:
        """Forget every undo history (and with it every dirty flag)."""
        for stack in self._stacks.values():
            self.undo_group.removeStack(stack)
            stack.deleteLater()
        self._stacks = {}

    def _set_patch(self, location: int, patch: Patch) -> None:
        """Replace a patch with content that is on the pedal (or a file): clean, no undo history."""
        self._patches[location] = patch
        stack = self._stacks.get(location)
        if stack is not None:
            stack.clear()
            stack.setClean()
        self._refresh_item(location)
        if location == self._location:
            self._show_patch(location)
        self._update_buttons()

    def select_location(self, location: int) -> None:
        self.patch_list.setCurrentRow(location - 1)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        self.undo_group.setActiveStack(self._stack(row + 1))
        self._show_patch(row + 1)
        if self.live_check.isChecked():
            self._go_live(row + 1)

    def _show_patch(self, location: int, select: int | None = None, keep: bool = False) -> None:
        previous = self.chain.selected_slot if keep else None
        self._location = location
        patch = self._patches.get(location)
        self.chain.set_patch(patch, self.catalog,
                             None if patch is None else edit.slot_problems(patch, self.catalog, self.allowed_ids))
        self.params.clear()
        self._update_header()
        if patch is None:
            self._update_buttons()
            return
        slots = {t.slot_index for t in self.chain.tiles()}
        wanted = select if select in slots else previous if previous in slots else None
        if wanted is None:
            real = [t for t in self.chain.tiles() if not t.is_empty]
            wanted = real[0].slot_index if real else None
        if wanted is not None:
            self.select_tile(wanted)
        self._update_buttons()

    def _update_header(self) -> None:
        location, patch = self._location, self.current_patch
        self.editor_row.setEnabled(patch is not None and not self._saving)
        if location is None:
            self.dsp_bar.setValue(0)
            self.dsp_bar.setFormat("DSP: n/a")
            return
        if patch is None:
            self.patch_title.setText(f"{self._display(location)}  -  empty")
            self.dsp_bar.setValue(0)
            self.dsp_bar.setFormat("DSP: n/a")
            return
        self.patch_title.setText(f"{self._display(location)}  {patch.name}  (volume {patch.volume})")
        for widget, setter, value in ((self.name_edit, self.name_edit.setText, patch.name),
                                      (self.volume_spin, self.volume_spin.setValue, patch.volume)):
            if (widget.text() if widget is self.name_edit else widget.value()) != value:
                widget.blockSignals(True)
                setter(value)
                widget.blockSignals(False)
        dsp = self.dsp_percent()
        self.dsp_bar.setValue(min(100, round(dsp)))
        self.dsp_bar.setFormat(f"DSP: {dsp:.0f}%" + ("  (over the limit)" if dsp > 100 else ""))
        self.dsp_bar.setStyleSheet("QProgressBar::chunk { background: #c0392b; }" if dsp > 100 else "")

    def save_blockers(self) -> list[str]:
        """Reasons the selected patch must not be written to the pedal (A1, A2, A3 and DSP checks)."""
        patch = self.current_patch
        return [] if patch is None else edit.save_blockers(patch, self.catalog, self.allowed_ids)

    def dsp_percent(self) -> float:
        patch = self.current_patch
        return 0.0 if patch is None else edit.dsp_percent(patch, self.catalog)

    # --------------------------------------------------------- chain/params

    def chain_tiles(self) -> list[EffectTile]:
        return self.chain.tiles()

    def param_rows(self) -> list[ParamRow]:
        return self.params.rows()

    def select_tile(self, slot_index: int) -> None:
        self.chain.select(slot_index)

    def _on_tile_selected(self, slot_index: int) -> None:
        patch = self.current_patch
        if patch is None:
            return
        if slot_index >= len(patch.effects) or patch.effects[slot_index].is_placeholder:
            self.params.clear("Empty slot: double-click an effect in the catalog or drop one here")
            return
        slot = patch.effects[slot_index]
        self.params.show_effect(slot, self.catalog.get(slot.effect_id))

    # ------------------------------------------------------------- editing

    def _store(self, location: int, patch: Patch | None, select: int | None) -> None:
        """Make ``patch`` the content of ``location`` (called by the undo commands)."""
        if patch is None:
            self._patches.pop(location, None)
        else:
            self._patches[location] = copy.deepcopy(patch)
        self._refresh_item(location)
        if location == self._location:
            if self._suppress_refresh:
                self._update_header()
            else:
                self._show_patch(location, select, keep=True)
        self._update_buttons()

    def _push(self, after: Patch, text: str, key: tuple | None = None, select: int | None = None,
              widget: bool = False) -> None:
        location = self._location
        assert location is not None
        before = self._patches.get(location)
        command = PatchEdit(self, location, before, after, text, key, self.chain.selected_slot, select)
        self._suppress_refresh = widget  # the widget that made the edit already shows it
        try:
            self._stack(location).push(command)
        finally:
            self._suppress_refresh = False

    def _edit(self, operation, text: str, *, key: tuple | None = None, select=None, widget: bool = False) -> bool:
        """Run ``operation(patch)``, push the result as an undo step; report errors."""
        patch = self.current_patch
        if patch is None:
            self.statusBar().showMessage("Select a patch to edit")
            return False
        if self._saving:
            return False
        try:
            after = operation(patch)
        except (ValueError, IndexError) as exc:
            self._report_error(str(exc))
            return False
        self._push(after, text, key, select(after) if callable(select) else select, widget)
        return True

    def undo(self) -> None:
        self.undo_group.undo()

    def redo(self) -> None:
        self.undo_group.redo()

    def rename_patch(self, name: str, widget: bool = False) -> None:
        self._edit(lambda p: edit.rename(p, name), "Rename patch", key=("name",), widget=widget)

    def set_patch_volume(self, volume: int, widget: bool = False) -> None:
        self._edit(lambda p: edit.set_volume(p, volume), "Change volume", key=("volume",), widget=widget)

    def set_param(self, slot_index: int, index: int, value: int, widget: bool = False) -> None:
        self._edit(lambda p: edit.set_param(p, slot_index, index, value), "Change parameter",
                   key=("param", slot_index, index), widget=widget)

    def set_effect_enabled(self, slot_index: int, enabled: bool, widget: bool = False) -> None:
        self._edit(lambda p: edit.set_enabled(p, slot_index, enabled),
                   "Switch effect " + ("on" if enabled else "off"), widget=widget)

    def replace_effect(self, slot_index: int, effect_id: int) -> None:
        if self.allowed_ids is not None and effect_id not in self.allowed_ids:
            info = self.catalog.get(effect_id)
            self._report_error(f"{info.name if info else hex(effect_id)} does not run on the A1 FOUR")
            return
        self._edit(lambda p: edit.replace_effect(p, slot_index, effect_id, self.catalog), "Replace effect",
                   select=lambda after: edit.slot_index_of(
                       after, edit.logical_index(self.current_patch.effects, slot_index)))

    def remove_effect(self, slot_index: int) -> None:
        self._edit(lambda p: edit.remove_effect(p, slot_index, self.catalog), "Remove effect")

    def move_effect(self, from_slot: int, to_slot: int) -> None:
        if from_slot == to_slot:
            return
        self._edit(lambda p: edit.move_effect(p, from_slot, to_slot, self.catalog), "Move effect",
                   select=lambda after: edit.slot_index_of(
                       after, edit.logical_index(self.current_patch.effects, to_slot)))

    # widget-originated edits ------------------------------------------------

    def _on_name_edited(self, text: str) -> None:
        self.rename_patch(text, widget=True)

    def _on_volume_changed(self, value: int) -> None:
        self.set_patch_volume(value, widget=True)

    def _on_param_changed(self, index: int, value: int) -> None:
        slot_index = self.chain.selected_slot
        if slot_index is None:
            return
        self.set_param(slot_index, index, value, widget=True)
        self._live_send(slot_index, index, value)

    def _on_power_toggled(self, slot_index: int, on: bool) -> None:
        self.set_effect_enabled(slot_index, on, widget=True)
        self._live_send(slot_index, None, 1 if on else 0)

    def _on_catalog_activated(self, effect_id: int) -> None:
        if self.current_patch is None:
            self.statusBar().showMessage("Select a patch first")
            return
        slot = self.chain.selected_slot
        if slot is None:
            empty = [t for t in self.chain.tiles() if t.is_empty]
            if not empty:
                self._report_error("Select the tile to replace first")
                return
            slot = empty[0].slot_index
        self.replace_effect(slot, effect_id)

    # --------------------------------------------------------------- live

    def _go_live(self, location: int) -> None:
        """Make ``location`` the pedal's current patch so live edits land on it."""
        if self._is_connected and self._worker is not None:
            self._live_location = location
            self._select_requested.emit(location)

    def _on_live_toggled(self, on: bool) -> None:
        if on and self._location is not None:
            self._go_live(self._location)
        elif not on:
            self._live_location = None

    def _live_send(self, slot_index: int, param_index: int | None, value: int) -> None:
        patch = self.current_patch
        if (not self.live_check.isChecked() or not self._is_connected or patch is None
                or self._live_location != self._location):
            return
        self._param_requested.emit(*live_message(patch, slot_index, param_index, value))

    # ---------------------------------------------------------------- files

    def _choose_save_file(self) -> None:
        patch = self.current_patch
        if patch is None or self._location is None:
            return
        suggestion = f"{self._display(self._location)}-{patch.name or 'patch'}.zptc"
        path, _ = QFileDialog.getSaveFileName(self, "Save patch as file", suggestion, "Zoom patch (*.zptc)")
        if path:
            self.save_file(Path(path))

    def _choose_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open patch file", str(Path.home()), "Zoom patch (*.zptc)")
        if path:
            self.open_file(Path(path))

    def save_file(self, path: Path) -> None:
        patch = self.current_patch
        if patch is None:
            self.statusBar().showMessage("Select a patch to save")
            return
        try:
            Path(path).write_bytes(build_zptc(patch))
        except (ValueError, OSError) as exc:
            self._report_error(f"Cannot save {path}: {exc}")
            return
        self.statusBar().showMessage(f"Saved {path}")

    def open_file(self, path: Path) -> None:
        """Load a ``.zptc`` file into the selected location as an undoable edit."""
        if self._location is None:
            self.statusBar().showMessage("Select a location to open the file into")
            return
        try:
            loaded = parse_zptc(Path(path).read_bytes())
        except (ValueError, OSError) as exc:
            self._report_error(f"Cannot open {path}: {exc}")
            return
        self._push(edit.with_fillers(loaded, self.catalog), "Open file")
        blockers = self.save_blockers()
        if blockers:
            self._report_error("This patch cannot be written to the pedal as it is: " + "; ".join(blockers[:3]))
            return
        self.statusBar().showMessage(f"Opened {Path(path).name} into {self._display(self._location)}")

    # ------------------------------------------------------- save to pedal

    def save_current_patch(self) -> None:
        """SAVE: back up the slot, write the patch (sent form), read it back and verify."""
        location, patch = self._location, self.current_patch
        if self._saving or location is None or patch is None:
            return
        if not self._is_connected or self._worker is None:
            self._report_error("Connect to the pedal to save")
            return
        blockers = self.save_blockers()
        if blockers:
            self._report_error("Cannot save: " + "; ".join(blockers))
            return
        if self.backup_dir is None:
            self._report_error("No backup folder configured: refusing to write to the pedal")
            return
        try:
            data = build_zptc(edit.sent_form(patch))
        except ValueError as exc:
            self._report_error(f"Cannot build the patch: {exc}")
            return
        self._set_saving(True)
        self.statusBar().showMessage(f"Saving patch {self._display(location)}...")
        self._save_requested.emit(location, data, self.backup_dir)

    def _set_saving(self, saving: bool) -> None:
        self._saving = saving
        for widget in (self.patch_panel, self.centre, self.catalog_panel):
            widget.setEnabled(not saving)
        self._update_buttons()

    @Slot(int, object, str)
    def _on_patch_saved(self, location: int, patch: Patch, backup: str) -> None:
        self._set_patch(location, patch)
        self.statusBar().showMessage(f"Saved patch {self._display(location)} (previous content: {backup})")

    @Slot(int, bool)
    def _on_save_finished(self, _location: int, ok: bool) -> None:
        self._set_saving(False)
        self.save_finished.emit(ok)

    # ------------------------------------------------------------- offline

    def confirm_discard(self, action: str) -> bool:
        """Ask before throwing away unsaved edits; True when there are none or the user agrees."""
        if not self.any_dirty():
            return True
        count = sum(1 for loc in self._stacks if self.is_dirty(loc))
        reply = QMessageBox.question(
            self, "Unsaved edits", f"{count} patch(es) have unsaved edits.\n{action} and discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return reply == QMessageBox.StandardButton.Discard

    def _choose_folder(self) -> None:
        start = str(self._offline_dir or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Open patch backup folder", start)
        if folder and self.confirm_discard("Opening another folder"):
            self.load_offline(Path(folder))

    def load_offline(self, folder: Path) -> None:
        """Load ``NNN.zptc`` files (NNN = location) from a backup folder."""
        folder = Path(folder)
        found: dict[int, Patch] = {}
        problems: list[str] = []
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            m = _PATCH_FILE.match(path.name)
            if not m:
                continue
            location = int(m.group(1))
            try:
                found[location] = parse_zptc(path.read_bytes())
            except (ValueError, OSError) as exc:
                problems.append(f"{path.name}: {exc}")
        if not folder.is_dir():
            self._report_error(f"Not a folder: {folder}")
            return
        self._offline_dir = folder
        self._patch_count = max(DEFAULT_PATCH_COUNT, max(found, default=0))
        self._patches = {}
        self._reset_edits()
        self._patches.update(found)
        self._rebuild_patch_list()
        self.connection_label.setText(f"Offline: {folder.name}")
        self.memory_bar.setValue(0)
        self.memory_bar.setFormat("Memory: n/a")
        self.statusBar().showMessage(f"Loaded {len(found)} patches from {folder}")
        if problems:
            self._report_error("; ".join(problems[:3]))
        self._update_buttons()
        self.patches_loaded.emit()

    def reload(self) -> None:
        if not (self._is_connected and self._worker is not None) and self._offline_dir is None:
            self.statusBar().showMessage("Nothing to reload: connect or open a folder first")
            return
        if not self.confirm_discard("Reloading"):
            return
        if self._is_connected and self._worker is not None:
            self._begin_pedal_read()
        else:
            self.load_offline(self._offline_dir)

    # --------------------------------------------------------------- pedal

    def _start_worker(self, factory: TransportFactory, timeout: float) -> None:
        self._thread = QThread(self)
        self._worker = PedalWorker(factory, timeout)
        self._worker.moveToThread(self._thread)
        w = self._worker
        w.connected.connect(self._on_connected)
        w.disconnected.connect(self._on_disconnected)
        w.patch_loaded.connect(self._on_patch_loaded)
        w.loading_finished.connect(self._on_loading_finished)
        w.disk_usage.connect(self._on_disk_usage)
        w.progress.connect(self._on_progress)
        w.patch_saved.connect(self._on_patch_saved)
        w.save_finished.connect(self._on_save_finished)
        w.error.connect(self._report_error)
        self._save_requested.connect(w.save_patch)
        self._queue_requested.connect(w.write_patches)
        self._backup_requested.connect(w.backup_all)
        w.queue_finished.connect(self._on_queue_done)
        w.backup_progress.connect(self._on_backup_progress)
        w.backup_finished.connect(self._on_backup_done)
        self._param_requested.connect(w.send_param)
        self._select_requested.connect(w.select_patch)
        self._thread.start()

    def start_connect(self) -> None:
        """Begin connecting to the pedal (no-op without a transport factory)."""
        if self._worker is None or self._is_connected:
            return
        if not self.confirm_discard("Connecting reloads every patch from the pedal"):
            return
        self.connect_button.setEnabled(False)
        self.statusBar().showMessage("Connecting...")
        self._worker.request("connect_pedal")

    def _on_connect_clicked(self) -> None:
        self.start_connect()

    def _on_disconnect_clicked(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.request("disconnect_pedal")

    def _begin_pedal_read(self) -> None:
        assert self._worker is not None
        self._patches = {}
        self._reset_edits()
        self._rebuild_patch_list()
        self.statusBar().showMessage("Reading patches...")
        self._worker.request("load_all_patches")
        self._worker.request("refresh_disk_usage")

    @Slot(object, object)
    def _on_connected(self, identity, info) -> None:
        self._is_connected = True
        self._offline_dir = None
        self._patch_count = info.count
        model = MODEL_NAMES.get(identity.model, f"model 0x{identity.model:02X}")
        firmware = bytes(identity.version).decode("ascii", "replace").strip("\x00 ")
        self.connection_label.setText(f"ZOOM {model}  -  firmware {firmware or '?'}")
        self._update_buttons()
        self._begin_pedal_read()

    @Slot()
    def _on_disconnected(self) -> None:
        self._is_connected = False
        self._live_location = None
        self.live_check.setChecked(False)
        self.connection_label.setText("Not connected")
        self.memory_bar.setValue(0)
        self.memory_bar.setFormat("Memory: n/a")
        self.statusBar().showMessage("Disconnected")
        self._update_buttons()

    @Slot(int, object)
    def _on_patch_loaded(self, location: int, patch: Patch) -> None:
        self._set_patch(location, patch)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"Reading patches {done}/{total}")

    @Slot()
    def _on_loading_finished(self) -> None:
        self.statusBar().showMessage(f"Loaded {len(self._patches)} patches from the pedal")
        self.patches_loaded.emit()

    @Slot(object)
    def _on_disk_usage(self, usage) -> None:
        pct = usage.used_percent
        self.memory_bar.setValue(round(pct))
        self.memory_bar.setFormat(f"Memory: {usage.used / 1024:.0f} / {usage.maximum / 1024:.0f} KB ({pct:.0f}%)")

    @Slot(str)
    def _report_error(self, message: str) -> None:
        self.statusBar().showMessage(f"Error: {message}", 15000)
        if self._worker is not None and not self._is_connected:
            self.connect_button.setEnabled(True)
        self.error_shown.emit(message)

    # --------------------------------------------------------------- close

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if not self._closed:
            if not self.confirm_discard("Closing"):
                event.ignore()
                return
            self._closed = True
            if self._worker is not None and self._thread is not None:
                self._worker.cancel()
                if self._thread.isRunning():
                    # blocks until the worker finished its current request, then closes the port
                    QMetaObject.invokeMethod(self._worker, "disconnect_pedal",
                                             Qt.ConnectionType.BlockingQueuedConnection)
                self._thread.quit()
                self._thread.wait(5000)
        super().closeEvent(event)
