"""Main window: patch list | signal chain + parameters | effect catalog, with undoable editing."""

from __future__ import annotations

import copy
import re
from pathlib import Path

from PySide6.QtCore import QMetaObject, QRegularExpression, QThread, Qt, Signal, Slot
from PySide6.QtGui import (
    QAction, QBrush, QColor, QKeySequence, QShortcut, QRegularExpressionValidator, QUndoCommand, QUndoGroup, QUndoStack,
)
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QScrollArea, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QMainWindow,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QStatusBar, QToolButton, QVBoxLayout, QWidget,
)

from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.effects.flst import pedal_filename
from zoomstudio.patches import edit
from zoomstudio.patches.model import NAME_MAX_LEN, VOLUME_MAX, Patch
from zoomstudio.patches.zptc import build_zptc, parse_zptc

from . import strings as S
from . import tokens
from .cards import ROLE_DIRTY, ROLE_NAME, ROLE_NUMBER, ROLE_STRIP
from .dialogs import ConfirmDialog
from .effects_manager import EffectsManager
from .fonts import display_font
from .glass import BackdropRoot, GlassMenu, GlassPanel, GlowHost
from .icons import icon, pixmap
from .painted import ConnectionPill, DotLabel, KeyChipButton, LiveSwitch, PaintedText, SectionLabel, StatusBar
from .bank_screen import BankMixin, BankScreen
from .library import LibraryMixin
from .tuner import TunerPanel
from . import favorites as favorites_module
from .favorites import FavoritesStore
from .widgets import CatalogPanel, ChainView, EffectTile, ParamPanel, ParamRow, PatchList
from .worker import PedalWorker, TransportFactory

PATCHES_WIDTH, CATALOG_WIDTH = 248, 368  # the prototype's column widths
DEFAULT_PATCH_COUNT = 50
DISPLAY_OFFSET = 9  # the pedal shows locations 1..50 as 10..59
MODEL_NAMES = {0x6E: "A1 FOUR"}
_PATCH_FILE = re.compile(r"^(\d+)\.zptc$", re.IGNORECASE)
_EMPTY_COLOR = tokens.color("text-tertiary")
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


class MainWindow(BankMixin, LibraryMixin, QMainWindow):
    patches_loaded = Signal()  # a full read (pedal) or folder load finished
    error_shown = Signal(str)
    save_finished = Signal(bool)  # a SAVE to the pedal ended (True: verified by read-back)
    _save_requested = Signal(int, object, object)
    _param_requested = Signal(int, int, int)
    _select_requested = Signal(int)
    _tuner_requested = Signal(bool)
    backup_finished = Signal(str, bool)  # backup-all ended: patches folder ("" if none), success
    queue_finished = Signal(object, int)  # a multi-slot write ended: locations written, failed location
    bank_finished = Signal(str, bool)  # a bank operation ended: "stash" / "load", success (after queue_finished)
    _backup_requested = Signal(object, bool, object)
    _queue_requested = Signal(object, object)
    _effects_state_requested = Signal()
    _effect_install_requested = Signal(str, object, object)
    _effect_remove_requested = Signal(str, object, object)
    _effect_repair_requested = Signal(str, object, object)

    def __init__(self, catalog: dict[int, EffectInfo], a1_ids: set[int] | None = None,
                 transport_factory: TransportFactory | None = None, installed_label: str = "pedal",
                 pedal_timeout: float = 3.0, backup_dir: Path | None = None,
                 library_dir: Path | None = None, favorites: FavoritesStore | None = None,
                 bank_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Zoom Studio")
        self.resize(1440, 900)
        self.setMinimumSize(1280, 760)
        self.catalog = catalog
        self.favorites = favorites if favorites is not None else FavoritesStore(favorites_module.default_path())
        self.allowed_ids = a1_ids  # effects that run on the A1 FOUR (None: no restriction)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else None
        self.library_dir = Path(library_dir) if library_dir is not None else None  # parent of backup-* folders
        self._init_library()
        self._init_bank(Path(bank_dir) if bank_dir is not None else None)
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
        self._tuner_on = False
        self._effects_open = False
        self._effects_busy = False
        self._patches_complete = False  # every patch of the pedal was read (and none failed)
        self._worker: PedalWorker | None = None
        self._thread: QThread | None = None

        self._build_ui(a1_ids, installed_label)
        self._rebuild_patch_list()
        if transport_factory is not None:
            self._start_worker(transport_factory, pedal_timeout)
        self._update_buttons()

    # ---------------------------------------------------------------- UI

    def _build_ui(self, a1_ids: set[int] | None, installed_label: str) -> None:
        backdrop_root = BackdropRoot()
        self.backdrop_root = backdrop_root
        header = GlassPanel(backdrop_root, "strong")
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 8, 16, 8)
        self.edit_button = self._menu_button(S.EDIT_MENU)
        self.library_button = self._menu_button(S.LIBRARY_MENU)
        self.connection_label = ConnectionPill(S.NOT_CONNECTED)
        self.connection_label.setMinimumWidth(190)
        self.memory_bar = QProgressBar()
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setValue(0)
        self.memory_bar.setFormat(S.MEMORY_NA)
        self.memory_bar.setTextVisible(False)  # the value is its own label: text over a 6 px bar cannot be read
        self.memory_bar.setFixedWidth(80)
        self.memory_value = QLabel(S.NOT_AVAILABLE)
        self.memory_value.setProperty("role", "value")
        self.connect_button = QPushButton(S.CONNECT)
        self.connect_button.setIcon(icon("plug"))
        self.disconnect_button = QPushButton(S.DISCONNECT)
        self.open_button = self._icon_button("folder", S.OPEN_FOLDER)
        self.reload_button = self._icon_button("reload", S.RELOAD)
        self.open_file_button = self._icon_button("file", S.OPEN_FILE)
        self.save_file_button = self._icon_button("filesave", S.SAVE_FILE)
        self.save_button = QPushButton(S.SAVE_TO_PEDAL)
        self.save_button.setProperty("primary", True)
        self.save_button.setIcon(icon("save", "on-accent"))
        self.tuner_button = KeyChipButton(S.TUNER, S.TUNER_KEY)
        self.tuner_button.setIcon(icon("tuner"))
        self.tuner_button.setCheckable(True)
        self.tuner_button.setToolTip(S.TUNER_TIP)
        self.effects_button = QPushButton(S.EFFECTS_BUTTON)
        self.effects_button.setIcon(icon("package"))
        self.effects_button.setCheckable(True)
        self.effects_button.setToolTip(S.EFFECTS_TIP)
        self.bank_button = self._icon_button("bank", S.BANK_TIP)  # icon only: the 1280 px header has no room for a word
        self.bank_button.setCheckable(True)
        self.bank_button.setAccessibleName(S.BANK_TITLE)
        self.live_check = LiveSwitch(S.LIVE)
        self.live_check.setToolTip(S.LIVE_TIP)
        self.live_check.setAccessibleName(S.LIVE_TIP)
        for w in (self.edit_button, self.library_button, self.connection_label):
            h.addWidget(w)
        h.addSpacing(8)
        h.addWidget(QLabel(S.MEMORY_LABEL))
        h.addWidget(self.memory_bar)
        h.addWidget(self.memory_value)
        h.addStretch(1)
        for w in (self.bank_button, self.effects_button, self.tuner_button, self.live_check, self.open_file_button, self.save_file_button,
                  self.open_button, self.reload_button, self.connect_button, self.disconnect_button):
            h.addWidget(w)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.disconnect_button.clicked.connect(self._on_disconnect_clicked)
        self.open_button.clicked.connect(self._choose_folder)
        self.reload_button.clicked.connect(self.reload)
        self.save_button.clicked.connect(self.save_current_patch)
        self.save_file_button.clicked.connect(self._choose_save_file)
        self.open_file_button.clicked.connect(self._choose_open_file)
        self.live_check.toggled.connect(self._on_live_toggled)
        self.tuner_button.toggled.connect(self._on_tuner_toggled)
        self.effects_button.toggled.connect(self._on_effects_toggled)
        self.bank_button.toggled.connect(self._on_bank_toggled)
        self.tuner_shortcut = QShortcut(QKeySequence("T"), self)
        self.tuner_shortcut.activated.connect(self._on_tuner_shortcut)

        self.undo_action = self.undo_group.createUndoAction(self, S.UNDO)
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.redo_action = self.undo_group.createRedoAction(self, S.REDO)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        self.undo_action.setIcon(icon("undo"))
        self.redo_action.setIcon(icon("redo"))
        for act in (self.undo_action, self.redo_action):
            self.addAction(act)  # the shortcuts must not depend on the menu being shown
        edit_menu = GlassMenu(self.edit_button, backdrop_root)
        self.edit_button.setMenu(edit_menu)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        note = edit_menu.addAction(S.EDIT_MENU_NOTE)
        note.setEnabled(False)

        self.patch_list = PatchList()
        self.patch_list.currentRowChanged.connect(self._on_row_changed)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.patches_caption = QLabel("")
        self.patches_caption.setProperty("role", "secondary")
        lv.addLayout(self._section_header(S.PATCHES, self.patches_caption))
        lv.addWidget(self.patch_list)
        self.patch_panel = left

        # the patch header: number and name are painted / styled in Exo 2 40; the name is edited in place
        self.patch_number = PaintedText("", display_font(tokens.px("text-title-size"), 300), "text-secondary",
                                        Qt.AlignmentFlag.AlignRight)
        self.patch_number.setMinimumWidth(56)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("patchName")
        self.name_edit.setMaxLength(NAME_MAX_LEN)
        self.name_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"[ -~]*")))
        self.name_edit.setMinimumWidth(230)
        self.name_edit.setPlaceholderText(S.NO_PATCH_SELECTED)
        self.name_edit.setToolTip(S.name_tip(NAME_MAX_LEN))
        self.name_edit.setAccessibleName(S.name_tip(NAME_MAX_LEN))
        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(0, VOLUME_MAX)
        self.volume_spin.setToolTip(S.VOLUME_TIP)
        self.volume_spin.setAccessibleName(S.VOLUME_TIP)
        self.volume_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.volume_spin.setFixedWidth(88)
        self.dsp_bar = QProgressBar()
        self.dsp_bar.setRange(0, 100)
        self.dsp_bar.setFormat(S.DSP_NA)
        self.dsp_bar.setTextVisible(False)
        self.dsp_bar.setFixedWidth(120)
        self.dsp_value = QLabel(S.NOT_AVAILABLE)
        self.dsp_value.setProperty("role", "value")
        self.dsp_alert = QLabel()
        self.dsp_alert.setPixmap(pixmap("alert", tokens.color("status-danger").name(), 18))
        self.dsp_alert.setToolTip(S.DSP_OVER_LIMIT)
        self.dsp_alert.setAccessibleName(S.DSP_OVER_LIMIT)
        self.dsp_alert.hide()
        undo_button, redo_button = QToolButton(), QToolButton()
        undo_button.setDefaultAction(self.undo_action)
        redo_button.setDefaultAction(self.redo_action)
        for b in (undo_button, redo_button):
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            b.setProperty("icon-only", True)
        self.dirty_label = DotLabel(S.UNSAVED_CHANGES)
        self.save_reason = QLabel("")
        self.save_reason.setProperty("role", "reason")
        self.save_reason.setWordWrap(True)
        self.save_reason.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.save_reason.setMaximumWidth(260)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(self.patch_number)
        title_row.addWidget(self.name_edit, stretch=1)
        title_row.addSpacing(10)
        title_row.addWidget(self.dirty_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        for widget in (QLabel(S.VOLUME), self.volume_spin):
            meta_row.addWidget(widget)
        meta_row.addSpacing(10)
        for widget in (QLabel(S.DSP_LABEL), self.dsp_bar, self.dsp_value, self.dsp_alert):
            meta_row.addWidget(widget)
        meta_row.addSpacing(6)
        for widget in (undo_button, redo_button):
            meta_row.addWidget(widget)
        meta_row.addStretch(1)
        self.editor_row = QWidget()  # everything the patch owns: disabled while there is none or a save runs
        left_col = QVBoxLayout(self.editor_row)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(0)
        left_col.addLayout(title_row)
        left_col.addLayout(meta_row)
        right_col = QVBoxLayout()
        right_col.setSpacing(0)
        right_col.addWidget(GlowHost(self.save_button, margin=8))
        right_col.addWidget(self.save_reason)
        right_col.addStretch(1)
        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.addWidget(self.editor_row, stretch=1)
        head_lay.addLayout(right_col)
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.volume_spin.valueChanged.connect(self._on_volume_changed)

        self.chain = ChainView()
        self.params = ParamPanel(installed_label)
        self.chain_scroll = QScrollArea()
        self.chain_scroll.setWidget(self.chain)
        self.chain_scroll.setWidgetResizable(True)
        self.chain_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chain_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chain_scroll.setFixedHeight(self.chain.height() + 2)
        self.chain_scroll.viewport().setAutoFillBackground(False)
        self.chain_caption = QLabel("")
        self.chain_caption.setProperty("role", "secondary")
        chain_block = QWidget()
        chain_lay = QVBoxLayout(chain_block)
        chain_lay.setContentsMargins(0, 0, 0, 0)
        chain_lay.setSpacing(6)
        chain_lay.addLayout(self._section_header(S.CHAIN_TITLE, self.chain_caption))
        chain_lay.addWidget(self.chain_scroll)
        centre = QWidget()
        cv = QVBoxLayout(centre)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(10)
        cv.addWidget(self._glass(head))
        cv.addWidget(self._glass(chain_block))
        cv.addWidget(self._glass(self.params), stretch=1)
        self.centre = centre
        self.chain.tile_selected.connect(self._on_tile_selected)
        self.chain.power_toggled.connect(self._on_power_toggled)
        self.chain.remove_requested.connect(self.remove_effect)
        self.chain.effect_dropped.connect(self.replace_effect)
        self.chain.tile_moved.connect(self.move_effect)
        self.params.param_changed.connect(self._on_param_changed)

        self.catalog_panel = CatalogPanel(self.catalog, a1_ids, installed_label, self.favorites)
        self.catalog_panel.effect_activated.connect(self._on_catalog_activated)
        self.catalog_panel.manage_requested.connect(self.open_effects_screen)

        left_panel, catalog_panel = self._glass(left), self._glass(self.catalog_panel)
        left_panel.setFixedWidth(PATCHES_WIDTH)
        catalog_panel.setFixedWidth(CATALOG_WIDTH)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(left_panel)
        splitter.addWidget(centre)
        splitter.addWidget(catalog_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)  # only the centre takes the spare width: 248 / rest / 368
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([PATCHES_WIDTH, 780, CATALOG_WIDTH])

        self.splitter = splitter
        self.tuner_panel = TunerPanel(backdrop_root)
        self.tuner_panel.hide()
        self.tuner_panel.exit_requested.connect(lambda: self.tuner_button.setChecked(False))
        self.effects_panel = EffectsManager(backdrop_root, self.catalog, a1_ids, self.favorites)
        self.effects_panel.hide()
        self.effects_panel.close_requested.connect(lambda: self.effects_button.setChecked(False))
        self.effects_panel.refresh_requested.connect(self._request_effects_state)
        self.effects_panel.install_requested.connect(self._on_effect_install)
        self.effects_panel.remove_requested.connect(self._on_effect_remove)
        self.effects_panel.repair_requested.connect(self._on_effect_repair)
        self.effects_panel.patch_requested.connect(self._open_patch_from_effects)
        self.bank_panel = BankScreen(backdrop_root)
        self.bank_panel.hide()
        self.bank_panel.close_requested.connect(lambda: self.bank_button.setChecked(False))
        self.bank_panel.stash_requested.connect(self.stash_position)
        self.bank_panel.load_requested.connect(self.load_from_bank)
        self.header = header
        self._status_bar = StatusBar()
        status_panel = GlassPanel(backdrop_root, "strong")
        status_lay = QHBoxLayout(status_panel)
        status_lay.setContentsMargins(14, 2, 14, 2)
        status_lay.addWidget(self._status_bar)
        root = backdrop_root
        rv = QVBoxLayout(root)
        rv.setContentsMargins(12, 10, 12, 8)
        rv.setSpacing(10)
        rv.addWidget(header)
        rv.addWidget(splitter, stretch=1)
        rv.addWidget(self.tuner_panel, stretch=1)
        rv.addWidget(self.effects_panel, stretch=1)
        rv.addWidget(self.bank_panel, stretch=1)
        rv.addWidget(status_panel)
        self.setCentralWidget(root)
        self._build_library_ui()
        self.statusBar().showMessage(S.READY)

    def statusBar(self) -> QStatusBar:  # noqa: N802 (Qt API)
        """The status bar lives inside a glass panel of the window, not in the main window's own slot."""
        return self._status_bar

    def _section_header(self, title: str, caption: QLabel) -> QHBoxLayout:
        """Exo 2 spaced-capitals title with a caption (a count, a hint) at its right."""
        row = QHBoxLayout()
        row.addWidget(SectionLabel(title))
        row.addStretch(1)
        row.addWidget(caption)
        return row

    def _menu_button(self, text: str) -> QToolButton:
        button = QToolButton()
        button.setText(text.replace("&", ""))
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setProperty("ghost", True)
        return button

    def _icon_button(self, name: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(icon(name))
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setProperty("icon-only", True)
        return button

    def _glass(self, content: QWidget) -> GlassPanel:
        """Put ``content`` on a glass panel (the content keeps its own layout and signals)."""
        panel = GlassPanel(self.backdrop_root)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addWidget(content)
        return panel

    def _set_connection(self, text: str, connected: bool, kind: str | None = None) -> None:
        """``kind`` is the colour of the dot: ok (connected), info (a folder is loaded) or none."""
        self.connection_label.setText(text)
        self.connection_label.setMinimumWidth(max(190, self.connection_label.sizeHint().width()))  # the text always fits
        self.connection_label.set_kind(kind or ("ok" if connected else "none"))
        self.connection_label.setProperty("connected", connected)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    def _update_buttons(self) -> None:
        can_connect = self._worker is not None
        self.connect_button.setEnabled(can_connect and not self._is_connected)
        self.disconnect_button.setEnabled(self._is_connected)
        self.reload_button.setEnabled(self._is_connected or self._offline_dir is not None)
        patch = self.current_patch
        self.open_file_button.setEnabled(self._location is not None and not self._saving)
        self.save_file_button.setEnabled(patch is not None)
        self.live_check.setEnabled(self._is_connected)
        self.tuner_button.setEnabled(self._is_connected and self._worker is not None and not self._saving
                                     and not self._effects_open and not self._bank_open)
        self.effects_button.setEnabled(not self._tuner_on and not self._saving and not self._effects_busy
                                       and not self._bank_open)
        self.bank_button.setVisible(not self._tuner_on)  # the tuner's «Salir del afinador» needs the room at 1440 px
        # the bank screen stays closable while its own write runs; it never opens over the tuner or the effects screen
        self.bank_button.setEnabled(not self._tuner_on and not self._effects_open and not self._effects_busy
                                    and (self._bank_open or not self._saving))
        self.effects_action.setEnabled(self.effects_button.isEnabled() and not self._effects_open)
        self.catalog_panel.manage_button.setEnabled(self.effects_action.isEnabled())
        blockers = self.save_blockers()
        dirty = self._location is not None and self.is_dirty(self._location)
        self.save_button.setEnabled(
            self._is_connected and patch is not None and dirty and not blockers and not self._saving)
        if blockers:
            tip = S.cannot_save(blockers[:3])
        elif not self._is_connected:
            tip = S.SAVE_NEEDS_CONNECTION
        elif not dirty:
            tip = S.SAVE_NO_EDITS
        else:
            tip = S.SAVE_TIP
        self.save_button.setToolTip(tip)
        self.save_reason.setText(tip)  # one help line under the button, whatever the state
        self.save_reason.setProperty("blocking", bool(blockers))
        self.save_reason.style().unpolish(self.save_reason)
        self.save_reason.style().polish(self.save_reason)
        self.dirty_label.setVisible(dirty)
        in_use = sum(1 for pt in self._patches.values() if any(not e.is_placeholder for e in pt.effects))
        self.patches_caption.setText(S.patches_caption(in_use, self._display(1), self._display(self._patch_count)))
        self.centralWidget().update()
        self._update_library_actions()
        if self._tuner_on or self._effects_open or self._bank_open:  # the tuner mutes the pedal; each screen owns the window
            for w in (self.save_button, self.open_file_button, self.save_file_button, self.live_check,
                      self.reload_button, self.connect_button, self.open_button):
                w.setEnabled(False)
            for act in (self.backup_action, self.backup_files_action, self.write_dirty_action, self.copy_action,
                        self.paste_action, self.clear_action, self.export_selected_action, self.export_all_action,
                        self.import_file_action, self.import_folder_action, self.stash_from_menu_action,
                        self.bank_action):
                act.setEnabled(False)
            if self._effects_busy:
                self.disconnect_button.setEnabled(False)
        if self._effects_open:
            self._refresh_effects_context()
        if self._bank_open:
            self._refresh_bank_context()

    # ------------------------------------------------------------- effects manager

    def _on_effects_toggled(self, on: bool) -> None:
        self._effects_open = on
        self.splitter.setEnabled(not on)
        self.splitter.setVisible(not on)
        self.effects_panel.setVisible(on)
        self.edit_button.setEnabled(not on)
        self.library_button.setEnabled(not on)
        self._update_buttons()
        if on:
            self._request_effects_state()

    def _request_effects_state(self) -> None:
        if self._worker is None or not self._is_connected:
            self.effects_panel.set_offline()
            return
        self.effects_panel.set_loading()
        self._effects_state_requested.emit()

    def effects_usage(self) -> dict[str, list[tuple[int, str]]]:
        """Pedal file name -> (display number, name) of the loaded patches that use the effect."""
        users: dict[str, list[tuple]] = {}
        for location in sorted(self._patches):
            patch = self._patches[location]
            files = {pedal_filename(info.filename) for slot in patch.effects
                     if (info := self.catalog.get(slot.effect_id)) is not None}
            for file in sorted(files):
                users.setdefault(file, []).append((self._display(location), patch.name, location,
                                                   self._chain_strip(patch)))
        return users

    def _refresh_effects_context(self) -> None:
        self.effects_panel.set_patch_usage(self._patches_complete and self._is_connected, self.any_dirty(),
                                           self.effects_usage())

    @property
    def effects_backup_dir(self) -> Path:
        """Where the effect list is backed up before it changes."""
        if self.backup_dir is not None:
            return self.backup_dir / "effects"
        from zoomstudio.__main__ import autosave_dir

        return autosave_dir() / "effects"

    def _on_effect_install(self, name: str, path) -> None:
        if self._worker is not None and self._is_connected:
            self._set_effects_busy(True, S.EFFECTS_BUSY_INSTALL)
            self._effects_repairing = False
            self._effect_install_requested.emit(name, path, self.effects_backup_dir)

    def _open_patch_from_effects(self, location: int) -> None:
        """A patch card of the effects screen: leave the screen (through its toggle) and select that patch."""
        self.effects_button.setChecked(False)
        self.select_location(location)

    def _on_effect_repair(self, name: str, path) -> None:
        if self._worker is not None and self._is_connected:
            self._set_effects_busy(True, S.EFFECTS_BUSY_REPAIR)
            self._effects_repairing = True  # the worker reports a repair as an install: name it right
            self._effect_repair_requested.emit(name, path, self.effects_backup_dir)

    def _on_effect_remove(self, name: str) -> None:
        if self._worker is not None and self._is_connected:
            self._set_effects_busy(True, S.EFFECTS_BUSY_REMOVE)
            in_use = {file: [user[0] for user in patches] for file, patches in self.effects_usage().items()}
            self._effect_remove_requested.emit(name, self.effects_backup_dir, in_use)

    def _set_effects_busy(self, busy: bool, text: str = "") -> None:
        self._effects_busy = busy
        self.effects_panel.set_busy(busy, text)
        self._update_buttons()

    @Slot(object, object, object)
    def _on_effects_state(self, flst_bytes, files, usage) -> None:
        self._set_memory(usage)
        self._refresh_effects_context()
        self.effects_panel.set_state(flst_bytes, files, usage)

    @Slot(str, bool)
    def _on_effect_changed(self, name: str, installed: bool) -> None:
        if getattr(self, "_effects_repairing", False):
            message = S.effects_repaired_ok
        else:
            message = S.effects_installed_ok if installed else S.effects_removed_ok
        self.statusBar().showMessage(message(name))

    @Slot(bool)
    def _on_effect_change_finished(self, _success: bool) -> None:
        self._effects_repairing = False
        self._set_effects_busy(False)
        self._request_effects_state()  # the lists and the memory always reflect the pedal, whatever happened

    # ------------------------------------------------------------- tuner

    def _on_tuner_shortcut(self) -> None:
        if self.tuner_button.isEnabled() or self.tuner_button.isChecked():
            self.tuner_button.toggle()

    def _on_tuner_toggled(self, on: bool) -> None:
        if self._worker is None or not self._is_connected:
            self._apply_tuner_state(False)
            return
        self._apply_tuner_state(on)
        self._tuner_requested.emit(on)

    def _apply_tuner_state(self, on: bool) -> None:
        """Show/hide the tuner panel and lock/unlock the editor (the pedal itself is driven by the worker)."""
        self._tuner_on = on
        self.tuner_button.setText(S.TUNER_EXIT if on else S.TUNER)
        if self.tuner_button.isChecked() != on:
            self.tuner_button.blockSignals(True)
            self.tuner_button.setChecked(on)
            self.tuner_button.blockSignals(False)
        if on:
            self.tuner_panel.show_reading(None, 0)
        self.splitter.setEnabled(not on)
        self.splitter.setVisible(not on)
        self.tuner_panel.setVisible(on)
        self.edit_button.setEnabled(not on)
        self.library_button.setEnabled(not on)
        self._update_buttons()

    @Slot(bool)
    def _on_tuner_state(self, on: bool) -> None:
        if self._tuner_on != on:  # the worker refused or lost the tuner
            self._apply_tuner_state(on)

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
        item.setData(ROLE_NUMBER, self._display(location))
        dirty = self.is_dirty(location)
        item.setData(ROLE_DIRTY, dirty)
        if patch is None:
            item.setText(f"{number}  -")
            item.setForeground(QBrush(_EMPTY_COLOR))
            item.setData(ROLE_NAME, "")
            item.setData(ROLE_STRIP, None)
        else:
            name = patch.name or S.UNNAMED
            item.setText(f"{number}  {name}{' *' if dirty else ''}")
            item.setForeground(QBrush(self.palette().text().color()))
            item.setData(ROLE_NAME, name)
            item.setData(ROLE_STRIP, self._chain_strip(patch))

    def _chain_strip(self, patch: Patch) -> list[tuple[str | None, int, bool]]:
        """One (group, slots, enabled) block per effect of the chain; ``None`` group for an empty slot."""
        slots, strip = patch.effects, []
        for i, slot in enumerate(slots):
            if slot.is_wide_filler:
                continue
            info = self.catalog.get(slot.effect_id)
            wide = not slot.is_empty and ((i + 1 < len(slots) and slots[i + 1].is_wide_filler)
                                          or (info is not None and info.is_wide))
            strip.append((None if slot.is_empty else (info.group if info else ""), 2 if wide else 1,
                          slot.enabled and not slot.is_empty))
        return strip

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

    def _update_catalog_target(self) -> None:
        patch, slot = self.current_patch, self.chain.selected_slot
        tiles = self.chain.tiles()
        tile = next((t for t in tiles if t.slot_index == slot), None)
        label = S.catalog_target(None if tile is None else slot, tile is not None and tile.is_empty,
                                 tile is not None and tile.is_wide)
        self.catalog_panel.set_target(label, patch is not None and tile is not None)
        self.catalog_panel.set_chain_effects(
            set() if patch is None else {s.effect_id for s in patch.effects if not s.is_placeholder})
        selected = None if patch is None or tile is None or tile.is_empty else self.catalog.get(patch.effects[slot].effect_id)
        self.catalog_panel.set_selected_group(selected.group if selected is not None else None)
        strip, text, replaced = [], S.NO_TARGET, 0.0
        if patch is not None and tile is not None:
            strip = [(None if t.is_empty else t.group, t.span, t.slot_index == slot) for t in tiles]
            text = S.catalog_destination(slot, tile.is_empty, tile.is_wide, tile.effect_name)
            info = None if tile.is_empty else self.catalog.get(patch.effects[slot].effect_id)
            replaced = info.dsp_load_percent if info else 0.0
        self.catalog_panel.set_destination(text, strip, self.dsp_percent(), replaced)

    def _update_header(self) -> None:
        self._update_catalog_target()
        location, patch = self._location, self.current_patch
        self.editor_row.setEnabled(patch is not None and not self._saving)
        self.patch_number.setText("" if location is None else str(self._display(location)))
        self.chain_caption.setText("" if patch is None else S.chain_caption(
            sum(1 for s_ in patch.effects if not s_.is_placeholder), len(patch.effects)))
        if patch is None:
            self.name_edit.blockSignals(True)
            self.name_edit.setText("")
            self.name_edit.blockSignals(False)
            self.name_edit.setPlaceholderText(S.NO_PATCH_SELECTED if location is None else S.PATCH_EMPTY_NAME)
            self._set_dsp(None)
            return
        for widget, setter, value in ((self.name_edit, self.name_edit.setText, patch.name),
                                      (self.volume_spin, self.volume_spin.setValue, patch.volume)):
            if (widget.text() if widget is self.name_edit else widget.value()) != value:
                widget.blockSignals(True)
                setter(value)
                widget.blockSignals(False)
        self.name_edit.setPlaceholderText(S.UNNAMED)
        self._set_dsp(self.dsp_percent())

    def _set_dsp(self, dsp: float | None) -> None:
        """Show the DSP load: the bar is only the fill, the value (and the over-the-limit warning) is a label."""
        over = dsp is not None and dsp > 100
        self.dsp_bar.setValue(0 if dsp is None else min(100, round(dsp)))
        self.dsp_bar.setFormat(S.DSP_NA if dsp is None else S.dsp_text(dsp))
        self.dsp_bar.setToolTip("" if dsp is None else S.dsp_text(dsp))
        self.dsp_value.setText(S.NOT_AVAILABLE if dsp is None else S.dsp_value(dsp))
        self.dsp_alert.setVisible(over)  # the warning mark: colour alone must not say «over the limit»
        for widget in (self.dsp_bar, self.dsp_value, self.dsp_alert):
            widget.setProperty("over", over)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

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
        self._update_catalog_target()
        patch = self.current_patch
        if patch is None:
            return
        if slot_index >= len(patch.effects) or patch.effects[slot_index].is_placeholder:
            self.params.show_empty(slot_index)
            return
        slot = patch.effects[slot_index]
        tile = next((t for t in self.chain.tiles() if t.slot_index == slot_index), None)
        self.params.show_effect(slot, self.catalog.get(slot.effect_id),
                                S.slot_label(slot_index, tile is not None and tile.is_wide))

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
            self.statusBar().showMessage(S.SELECT_PATCH_TO_EDIT)
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
        self._edit(lambda p: edit.rename(p, name), S.UNDO_RENAME, key=("name",), widget=widget)

    def set_patch_volume(self, volume: int, widget: bool = False) -> None:
        self._edit(lambda p: edit.set_volume(p, volume), S.UNDO_VOLUME, key=("volume",), widget=widget)

    def set_param(self, slot_index: int, index: int, value: int, widget: bool = False) -> None:
        self._edit(lambda p: edit.set_param(p, slot_index, index, value), S.UNDO_PARAM,
                   key=("param", slot_index, index), widget=widget)

    def set_effect_enabled(self, slot_index: int, enabled: bool, widget: bool = False) -> None:
        self._edit(lambda p: edit.set_enabled(p, slot_index, enabled),
                   S.undo_power(enabled), widget=widget)

    def replace_effect(self, slot_index: int, effect_id: int) -> None:
        if self.allowed_ids is not None and effect_id not in self.allowed_ids:
            info = self.catalog.get(effect_id)
            self._report_error(S.not_runnable(info.name if info else hex(effect_id)))
            return
        self._edit(lambda p: edit.replace_effect(p, slot_index, effect_id, self.catalog), S.UNDO_REPLACE,
                   select=lambda after: edit.slot_index_of(
                       after, edit.logical_index(self.current_patch.effects, slot_index)))

    def remove_effect(self, slot_index: int) -> None:
        self._edit(lambda p: edit.remove_effect(p, slot_index, self.catalog), S.UNDO_REMOVE)

    def move_effect(self, from_slot: int, to_slot: int) -> None:
        if from_slot == to_slot:
            return
        self._edit(lambda p: edit.move_effect(p, from_slot, to_slot, self.catalog), S.UNDO_MOVE,
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
            self.statusBar().showMessage(S.SELECT_PATCH_FIRST)
            return
        slot = self.chain.selected_slot
        if slot is None:
            empty = [t for t in self.chain.tiles() if t.is_empty]
            if not empty:
                self._report_error(S.SELECT_PEDAL_TO_REPLACE)
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
        path, _ = QFileDialog.getSaveFileName(self, S.SAVE_PATCH_FILE, suggestion, S.PATCH_FILTER)
        if path:
            self.save_file(Path(path))

    def _choose_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, S.OPEN_PATCH_FILE, str(Path.home()), S.PATCH_FILTER)
        if path:
            self.open_file(Path(path))

    def save_file(self, path: Path) -> None:
        patch = self.current_patch
        if patch is None:
            self.statusBar().showMessage(S.SELECT_PATCH_TO_SAVE)
            return
        try:
            Path(path).write_bytes(build_zptc(patch))
        except (ValueError, OSError) as exc:
            self._report_error(S.cannot_save_file(path, exc))
            return
        self.statusBar().showMessage(S.saved_file(path))

    def open_file(self, path: Path) -> None:
        """Load a ``.zptc`` file into the selected location as an undoable edit."""
        if self._location is None:
            self.statusBar().showMessage(S.SELECT_LOCATION_FOR_FILE)
            return
        try:
            loaded = parse_zptc(Path(path).read_bytes())
        except (ValueError, OSError) as exc:
            self._report_error(S.cannot_open_file(path, exc))
            return
        self._push(edit.with_fillers(loaded, self.catalog), S.UNDO_OPEN_FILE)
        blockers = self.save_blockers()
        if blockers:
            self._report_error(S.patch_not_writable(blockers[:3]))
            return
        self.statusBar().showMessage(S.opened_into(Path(path).name, self._display(self._location)))

    # ------------------------------------------------------- save to pedal

    def save_current_patch(self) -> None:
        """SAVE: back up the slot, write the patch (sent form), read it back and verify."""
        location, patch = self._location, self.current_patch
        if self._saving or location is None or patch is None:
            return
        if not self._is_connected or self._worker is None:
            self._report_error(S.SAVE_NEEDS_CONNECTION)
            return
        blockers = self.save_blockers()
        if blockers:
            self._report_error(S.cannot_save(blockers))
            return
        if self.backup_dir is None:
            self._report_error(S.ERR_NO_BACKUP_DIR)
            return
        try:
            data = build_zptc(edit.sent_form(patch))
        except ValueError as exc:
            self._report_error(S.build_failed(exc))
            return
        self._set_saving(True)
        self.statusBar().showMessage(S.saving(self._display(location)))
        self._save_requested.emit(location, data, self.backup_dir)

    def _set_saving(self, saving: bool) -> None:
        self._saving = saving
        for widget in (self.patch_panel, self.centre, self.catalog_panel):
            widget.setEnabled(not saving)
        self._update_buttons()

    @Slot(int, object, str)
    def _on_patch_saved(self, location: int, patch: Patch, backup: str) -> None:
        self._set_patch(location, patch)
        self.statusBar().showMessage(S.saved(self._display(location), backup))

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
        return ConfirmDialog.ask(self, S.DISCARD_TITLE, S.discard_text(count, action), S.DISCARD_ACCEPT, danger=True)

    def _choose_folder(self) -> None:
        start = str(self._offline_dir or Path.home())
        folder = QFileDialog.getExistingDirectory(self, S.OPEN_BACKUP_FOLDER, start)
        if folder and self.confirm_discard(S.DISCARD_OPEN_FOLDER):
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
            self._report_error(S.not_a_folder(folder))
            return
        self._offline_dir = folder
        self._patch_count = max(DEFAULT_PATCH_COUNT, max(found, default=0))
        self._patches = {}
        self._reset_edits()
        self._patches.update(found)
        self._rebuild_patch_list()
        self._set_connection(S.offline(folder.name), False, "info")
        self._set_memory(None)
        self.statusBar().showMessage(S.loaded_from_folder(len(found), folder))
        if problems:
            self._report_error("; ".join(problems[:3]))
        self._update_buttons()
        self.patches_loaded.emit()

    def reload(self) -> None:
        if not (self._is_connected and self._worker is not None) and self._offline_dir is None:
            self.statusBar().showMessage(S.NOTHING_TO_RELOAD)
            return
        if not self.confirm_discard(S.DISCARD_RELOAD):
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
        self._tuner_requested.connect(w.set_tuner)
        self._effects_state_requested.connect(w.load_effects_state)
        self._effect_install_requested.connect(w.install_effect_file)
        self._effect_remove_requested.connect(w.remove_effect_file)
        self._effect_repair_requested.connect(w.repair_effect_file)
        w.effects_state.connect(self._on_effects_state)
        w.effects_state_failed.connect(self.effects_panel.set_failed)
        w.effect_changed.connect(self._on_effect_changed)
        w.effect_change_finished.connect(self._on_effect_change_finished)
        w.tuner_reading.connect(self.tuner_panel.show_reading)
        w.tuner_state.connect(self._on_tuner_state)
        self._thread.start()

    def start_connect(self) -> None:
        """Begin connecting to the pedal (no-op without a transport factory)."""
        if self._worker is None or self._is_connected:
            return
        if not self.confirm_discard(S.DISCARD_CONNECT):
            return
        self.connect_button.setEnabled(False)
        self.statusBar().showMessage(S.CONNECTING)
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
        self._patches_complete = False
        self._reset_edits()
        self._rebuild_patch_list()
        self.statusBar().showMessage(S.READING_PATCHES)
        self._update_buttons()
        self._worker.request("load_all_patches")
        self._worker.request("refresh_disk_usage")

    @Slot(object, object)
    def _on_connected(self, identity, info) -> None:
        self._is_connected = True
        self._offline_dir = None
        self._patch_count = info.count
        model = MODEL_NAMES.get(identity.model, S.unknown_model(identity.model))
        firmware = bytes(identity.version).decode("ascii", "replace").strip("\x00 ")
        self._set_connection(S.connected(model), True)
        self.connection_label.setToolTip(S.firmware_tip(firmware or "?"))
        self._update_buttons()
        self._begin_pedal_read()

    @Slot()
    def _on_disconnected(self) -> None:
        self._is_connected = False
        self._apply_tuner_state(False)
        self._live_location = None
        self.live_check.setChecked(False)
        self._set_connection(S.NOT_CONNECTED, False)
        self.connection_label.setToolTip("")
        self._set_memory(None)
        if self._effects_open:
            self.effects_panel.set_offline()
        self.statusBar().showMessage(S.DISCONNECTED)
        self._update_buttons()

    @Slot(int, object)
    def _on_patch_loaded(self, location: int, patch: Patch) -> None:
        self._set_patch(location, patch)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(S.reading_progress(done, total))

    @Slot()
    def _on_loading_finished(self) -> None:
        self._patches_complete = len(self._patches) >= self._patch_count
        self._update_buttons()
        self.statusBar().showMessage(S.loaded_from_pedal(len(self._patches)))
        self.patches_loaded.emit()

    @Slot(object)
    def _on_disk_usage(self, usage) -> None:
        self._set_memory(usage)

    def _set_memory(self, usage) -> None:
        """Memory of the pedal: the bar is the fill, the percentage is a label, the exact figure is the tooltip."""
        if usage is None:
            self.memory_bar.setValue(0)
            self.memory_bar.setFormat(S.MEMORY_NA)
            self.memory_value.setText(S.NOT_AVAILABLE)
            tip = S.MEMORY_NA
        else:
            pct = usage.used_percent
            self.memory_bar.setValue(round(pct))
            tip = S.memory_text(usage.used / 1024, usage.maximum / 1024, pct)
            self.memory_bar.setFormat(tip)
            self.memory_value.setText(f"{pct:.0f} %")
        for widget in (self.memory_bar, self.memory_value):
            widget.setToolTip(tip)

    @Slot(str)
    def _report_error(self, message: str) -> None:
        self.statusBar().show_error(S.error(message), 15000)
        if self._worker is not None and not self._is_connected:
            self.connect_button.setEnabled(True)
        self.error_shown.emit(message)

    # --------------------------------------------------------------- close

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if not self._closed:
            if not self.confirm_discard(S.DISCARD_CLOSE):
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
