"""Main window: patch list | signal chain + parameters | effect catalog, with undoable editing."""

from __future__ import annotations

import copy
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QMetaObject, QRegularExpression, QSize, QThread, Qt, Signal, Slot
from PySide6.QtGui import (
    QAction, QBrush, QColor, QKeySequence, QShortcut, QRegularExpressionValidator, QUndoCommand, QUndoGroup, QUndoStack,
)
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QScrollArea, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QMainWindow,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QStatusBar, QToolButton, QVBoxLayout, QWidget,
)

from jmc_guitar_zoom.effects.catalog import EffectInfo
from jmc_guitar_zoom.effects import flst
from jmc_guitar_zoom.effects.flst import pedal_filename
from jmc_guitar_zoom.patches import edit
from jmc_guitar_zoom.patches.bank import BankError
from jmc_guitar_zoom.patches.model import NAME_MAX_LEN, VOLUME_MAX, Patch
from jmc_guitar_zoom.patches.zptc import build_zptc, parse_zptc

from . import strings as S
from . import tokens
from .cards import ROLE_DIRTY, ROLE_MISSING, ROLE_NAME, ROLE_NUMBER, ROLE_STRIP
from .dialogs import ConfirmDialog
from .effects_manager import Entry, EffectsManager, build_entries
from .fonts import display_font
from .glass import BackdropRoot, GlassMenu, GlassPanel, GlowHost
from .icons import icon, pixmap
from . import memory
from .painted import ConnectionPill, DotLabel, KeyChipButton, LiveSwitch, PaintedText, SectionLabel, StatusBar
from .bank_screen import BankMixin, BankScreen
from .library import LibraryMixin
from .tuner import TunerPanel
from .update_view import UpdateMixin
from . import favorites as favorites_module
from jmc_guitar_zoom.effects import models as pedal_models
from jmc_guitar_zoom.effects.models import A1_FOUR, PedalModel, model_id_from_identity

from . import settings as settings_module
from .favorites import FavoritesStore
from .settings import TargetStore
from .widgets import CatalogPanel, ChainView, EffectTile, MissingButton, ParamPanel, ParamRow, PatchList
from .worker import PedalWorker, TransportFactory

PATCHES_WIDTH, CATALOG_WIDTH = 248, 368  # the prototype's column widths (their maximum: compact windows narrow them)
PATCHES_MIN, CATALOG_MIN = 220, 330
DISCARD_SHORTCUT = "Ctrl+R"  # revert the current patch to its last saved version (Ctrl+Z/Y/C/V and T are taken)
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


def live_restore_messages(current: Patch, baseline: Patch) -> list[tuple[int, int, int]]:
    """``(slot, param, value)`` triples that put the pedal's edit buffer back to ``baseline`` (live path only).

    Slots whose effect differs from ``current`` are skipped: a parameter message cannot swap an effect.
    The name is sent character by character (slot 9) and the volume as slot 10, as in ``PedalClient``.
    """
    messages: list[tuple[int, int, int]] = []
    for index, (now, base) in enumerate(zip(current.effects, baseline.effects)):
        if base.is_empty or base.is_wide_filler or base.is_placeholder or now.effect_id != base.effect_id:
            continue
        messages.append((index, 0, 1 if base.enabled else 0))
        messages.extend((index, i + 2, value) for i, value in enumerate(base.params))
    for position, char in enumerate(baseline.name.ljust(NAME_MAX_LEN)[:NAME_MAX_LEN]):
        messages.append((0x09, position, ord(char)))
    messages.append((0x0A, 0, baseline.volume))
    return messages


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


class MainWindow(UpdateMixin, BankMixin, LibraryMixin, QMainWindow):
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
    _update_check_requested = Signal(object, bool, object, bool)  # model id, all models, firmware, background
    _update_download_requested = Signal(object)
    _update_checked_relay = Signal(object, str, bool, bool)  # the updater thread's results, delivered in this thread
    _update_progress_relay = Signal(int, int, str)
    _update_downloaded_relay = Signal(object, object, str)
    update_checked = Signal()  # an effect-channel check ended (whatever its outcome)
    update_downloaded = Signal()  # an effect download ended and the catalog was reloaded

    def __init__(self, catalog: dict[int, EffectInfo], a1_ids: set[int] | None = None,
                 transport_factory: TransportFactory | None = None, installed_label: str = "pedal",
                 pedal_timeout: float = 3.0, backup_dir: Path | None = None,
                 library_dir: Path | None = None, favorites: FavoritesStore | None = None,
                 bank_dir: Path | None = None, models: dict[int, PedalModel] | None = None,
                 target_store: TargetStore | None = None, extra_ids: set[int] | None = None,
                 updater=None, reload_sources=None, update_store=None, online=None, update_clock=None) -> None:
        super().__init__()
        self.setWindowTitle("JMC Guitar Zoom · no oficial, no afiliada a Zoom Corporation")
        self.resize(1440, 900)
        self.setMinimumSize(1280, 760)
        self.catalog = catalog
        self.favorites = favorites if favorites is not None else FavoritesStore(favorites_module.default_path())
        # the pedal models Guitar Lab lists; ``a1_ids`` alone describes just the A1 FOUR (None: no restriction at all)
        self.models: dict[int, PedalModel] = models if models is not None else (
            {A1_FOUR: PedalModel(A1_FOUR, "A1 FOUR", frozenset(a1_ids))} if a1_ids is not None else {})
        self._extra_ids = set(extra_ids or ())  # effects installed on the pedal that the list omits
        self.target_store = target_store if target_store is not None else TargetStore(settings_module.default_path())
        self.connected_model: int | None = None
        self.target_model = self._initial_target()
        self.allowed_ids = self._ids_for(self.target_model)  # effects the target pedal runs (None: no restriction)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else None
        self.library_dir = Path(library_dir) if library_dir is not None else None  # parent of backup-* folders
        self._init_library()
        self._init_updates(updater, reload_sources, update_store, online, update_clock)
        self._init_bank(Path(bank_dir) if bank_dir is not None else None)
        self._patches: dict[int, Patch] = {}
        self._stacks: dict[int, QUndoStack] = {}
        self._baselines: dict[int, Patch] = {}  # location -> last saved version (while it has unsaved edits)
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
        self._installed_files: set[str] | None = None  # pedal files installed and present; None: not read (nothing guessed)
        self._installed_ids: set[int] | None = None  # the catalog effects those files are
        self._removal: dict | None = None  # the «Quitar seleccionados» run in progress
        self._pedal_state: tuple[bytes, list[str]] | None = None  # the last list and file names the pedal reported
        self._pedal_entries: list[Entry] = []  # the installed and available entries of the last read
        self._pending_add: tuple[int, int, int] | None = None  # (location, slot, effect ID) waiting for its install
        self._patches_complete = False  # every patch of the pedal was read (and none failed)
        self._worker: PedalWorker | None = None
        self._thread: QThread | None = None

        self._build_ui(installed_label)
        self._rebuild_patch_list()
        if transport_factory is not None:
            self._start_worker(transport_factory, pedal_timeout)
        self._update_buttons()

    # ---------------------------------------------------------------- UI

    def _build_ui(self, installed_label: str) -> None:
        backdrop_root = BackdropRoot()
        self.backdrop_root = backdrop_root
        header = GlassPanel(backdrop_root, "strong")
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 8, 16, 8)
        self.edit_button = self._menu_button(S.EDIT_MENU)
        self.library_button = self._menu_button(S.LIBRARY_MENU)
        self.connection_label = ConnectionPill(S.NOT_CONNECTED)
        self.memory_bar = QProgressBar()
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setValue(0)
        self.memory_bar.setFormat(S.MEMORY_NA)
        self.memory_bar.setTextVisible(False)  # the value is its own label: text over a 6 px bar cannot be read
        self.memory_bar.setFixedWidth(80)
        self.memory_value = QLabel(S.NOT_AVAILABLE)
        self.memory_value.setProperty("role", "value")
        self.memory_icon = QLabel()  # the warning icon of a low or critical memory (the word, the icon and the tooltip
        self.memory_icon.hide()      # say it besides the colour)
        self.memory_word = QLabel("")
        self.memory_word.hide()
        self.connect_button = QPushButton(S.CONNECT)
        self.connect_button.setIcon(icon("plug"))
        self.disconnect_button = QPushButton(S.DISCONNECT)
        self.disconnect_button.setIcon(icon("unplug"))
        self.open_button = self._icon_button("folder", S.OPEN_FOLDER)
        self.reload_button = self._icon_button("reload", S.RELOAD)
        self.open_file_button = self._icon_button("file", S.OPEN_FILE)
        self.save_file_button = self._icon_button("filesave", S.SAVE_FILE)
        self.save_button = QPushButton()  # icon only: its name and the reason it is (not) available are the tooltip
        self.save_button.setProperty("primary", True)
        self.save_button.setProperty("iconOnly", True)
        self.save_button.setIcon(icon("save", "on-accent", 24))
        self.save_button.setIconSize(QSize(24, 24))
        self.save_button.setAccessibleName(S.SAVE_TO_PEDAL)
        # the revert button: a different shape (counter-clockwise arrow) and the warning family, never red
        self.discard_button = QPushButton()
        self.discard_button.setProperty("revert", True)
        self.discard_button.setProperty("iconOnly", True)
        self.discard_button.setIcon(icon("reset", "status-warn", 24))
        self.discard_button.setIconSize(QSize(24, 24))
        self.discard_button.setAccessibleName(S.DISCARD_CHANGES_TIP)
        self.discard_button.setToolTip(S.discard_tooltip(DISCARD_SHORTCUT))
        self.discard_button.clicked.connect(lambda: self.discard_changes())
        self.tuner_button = KeyChipButton(S.TUNER, S.TUNER_KEY)
        self.tuner_button.setIcon(icon("tuner"))
        self.tuner_button.setCheckable(True)
        self.tuner_button.setToolTip(S.TUNER_TIP)
        # the effects screen has no button in the bar: its open state is this checkable action, driven by the
        # catalog's «Administrar» button, the Biblioteca menu entry and the screen's own «Cerrar»
        self.effects_toggle = QAction(S.EFFECTS_BUTTON, self)
        self.effects_toggle.setCheckable(True)
        self.update_toggle = QAction(S.LIBRARY_UPDATE, self)  # the update view's open state (no button in the bar)
        self.update_toggle.setCheckable(True)
        self.update_toggle.toggled.connect(self._on_update_toggled)
        self.bank_button = self._icon_button("bank", S.BANK_TIP)  # icon only: the 1280 px header has no room for a word
        self.bank_button.setCheckable(True)
        self.bank_button.setAccessibleName(S.BANK_TITLE)
        self.live_check = LiveSwitch(S.LIVE)
        self.live_check.setToolTip(S.LIVE_TIP)
        self.live_check.setAccessibleName(S.LIVE_TIP)
        for w in (self.edit_button, self.library_button, self.connection_label):
            h.addWidget(w)
        h.addSpacing(8)
        self.memory_caption = QLabel(S.MEMORY_LABEL)
        h.addWidget(self.memory_caption)
        h.addWidget(self.memory_bar)
        h.addWidget(self.memory_icon)
        h.addWidget(self.memory_word)
        h.addWidget(self.memory_value)
        h.addStretch(1)
        for w in (self.bank_button, self.tuner_button, self.live_check, self.open_file_button, self.save_file_button,
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
        self.effects_toggle.toggled.connect(self._on_effects_toggled)
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
        self.discard_action = QAction(S.DISCARD_ACCEPT, self)
        self.discard_action.setShortcut(QKeySequence(DISCARD_SHORTCUT))
        self.discard_action.setIcon(icon("reset", "status-warn"))
        self.discard_action.triggered.connect(lambda _c=False: self.discard_changes())
        self.addAction(self.discard_action)  # the shortcut must not depend on the menu being shown
        edit_menu.addAction(self.discard_action)
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
        self.missing_button = MissingButton()  # «⚠ 3»: patches that use effects the pedal lacks; click: the next one
        self.missing_button.clicked.connect(self.select_next_missing)
        lv.addLayout(self._section_header(S.PATCHES, self.patches_caption))
        missing_row = QHBoxLayout()  # under the caption: the 220 px column has no room for it on the title line
        missing_row.addStretch(1)
        missing_row.addWidget(self.missing_button)
        lv.addLayout(missing_row)
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
        self.name_edit.setMinimumWidth(200)
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
        self.dsp_bar.setMinimumWidth(56)  # shrinks in a compact window
        self.dsp_bar.setMaximumWidth(120)
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
        right_col = QHBoxLayout()
        right_col.setSpacing(0)
        right_col.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_col.addWidget(GlowHost(self.save_button, margin=8), alignment=Qt.AlignmentFlag.AlignTop)
        right_col.addWidget(GlowHost(self.discard_button, token="glow-accent", margin=8), alignment=Qt.AlignmentFlag.AlignTop)
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
        self.chain.install_requested.connect(self._on_tile_install)
        self.chain.tile_moved.connect(self.move_effect)
        self.params.param_changed.connect(self._on_param_changed)

        self.catalog_panel = CatalogPanel(self.catalog, self.allowed_ids, installed_label, self.favorites,
                                         self._target_name(), self._supported_pedals(), self.target_model)
        self.catalog_panel.effect_activated.connect(self._on_catalog_activated)
        self.catalog_panel.manage_requested.connect(self.open_effects_screen)
        self.catalog_panel.install_requested.connect(self.quick_install)
        self.catalog_panel.pedal_chosen.connect(self._set_target)

        left_panel, catalog_panel = self._glass(left), self._glass(self.catalog_panel)
        left_panel.setMinimumWidth(PATCHES_MIN)
        left_panel.setMaximumWidth(PATCHES_WIDTH)
        catalog_panel.setMinimumWidth(CATALOG_MIN)
        catalog_panel.setMaximumWidth(CATALOG_WIDTH)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(left_panel)
        self.centre_scroll = QScrollArea()  # a window too short for the centre scrolls it instead of squeezing it
        self.centre_scroll.setWidget(centre)
        self.centre_scroll.setWidgetResizable(True)
        self.centre_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.centre_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.centre_scroll.viewport().setAutoFillBackground(False)
        splitter.addWidget(self.centre_scroll)
        splitter.addWidget(catalog_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)  # only the centre takes the spare width: 248 / rest / 368
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([PATCHES_WIDTH, 780, CATALOG_WIDTH])

        self.splitter = splitter
        self.tuner_panel = TunerPanel(backdrop_root)
        self.tuner_panel.hide()
        self.tuner_panel.exit_requested.connect(lambda: self.tuner_button.setChecked(False))
        self.effects_panel = EffectsManager(backdrop_root, self.catalog, self.allowed_ids, self.favorites)
        self.effects_panel.hide()
        self.effects_panel.close_requested.connect(lambda: self.effects_toggle.setChecked(False))
        self.effects_panel.refresh_requested.connect(self._request_effects_state)
        self.effects_panel.remove_many_requested.connect(self._on_effects_remove_many)
        self.effects_panel.update_requested.connect(self.open_update_view)
        self.effects_panel.set_update_available(self._updater is not None)
        self.effects_panel.install_requested.connect(self._on_effect_install)
        self.effects_panel.remove_requested.connect(self._on_effect_remove)
        self.effects_panel.repair_requested.connect(self._on_effect_repair)
        self._sync_effects_pedals()
        self.effects_panel.patch_requested.connect(self._open_patch_from_effects)
        self.bank_panel = BankScreen(backdrop_root)
        self.bank_panel.hide()
        self.bank_panel.close_requested.connect(lambda: self.bank_button.setChecked(False))
        self.bank_panel.stash_requested.connect(self.stash_position)
        self.bank_panel.load_requested.connect(self.load_from_bank)
        self.bank_panel.rename_requested.connect(self.rename_entry)
        self.bank_panel.delete_requested.connect(self.delete_entry)
        self.update_panel = self._build_update_panel(backdrop_root)
        self.header = header
        self._header_level = 0
        self._fitting_header = False
        header.installEventFilter(self)
        self._fit_header()
        self._status_bar = StatusBar()
        status_panel = GlassPanel(backdrop_root, "strong")
        status_lay = QHBoxLayout(status_panel)
        status_lay.setContentsMargins(14, 2, 14, 2)
        status_lay.addWidget(self._status_bar)
        root = backdrop_root
        rv = QVBoxLayout(root)
        rv.setContentsMargins(12, 10, 12, 8)
        rv.setSpacing(10)
        self.pedal_notice = QLabel("")  # a calm banner for a pedal that is detected but not editable yet
        self.pedal_notice.setProperty("role", "notice")
        self.pedal_notice.setWordWrap(True)
        self.pedal_notice.hide()
        rv.addWidget(header)
        rv.addWidget(self.pedal_notice)
        rv.addWidget(splitter, stretch=1)
        rv.addWidget(self.tuner_panel, stretch=1)
        rv.addWidget(self.effects_panel, stretch=1)
        rv.addWidget(self.bank_panel, stretch=1)
        rv.addWidget(self.update_panel, stretch=1)
        rv.addWidget(status_panel)
        self.setCentralWidget(root)
        self._build_library_ui()
        self._build_update_ui()
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
        self._fit_header()
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
        self.live_check.setEnabled(self._can_write)
        self.tuner_button.setEnabled(self._is_connected and self._worker is not None and not self._saving
                                     and not self._effects_open and not self._bank_open and not self._update_open)
        self.effects_toggle.setEnabled(not self._tuner_on and not self._saving and not self._effects_busy
                                       and not self._bank_open and not self._update_open)
        self.update_toggle.setEnabled(self._updater is not None and not self._tuner_on and not self._saving
                                      and not self._effects_busy and not self._bank_open
                                      and not self._update_busy)
        self.update_action.setEnabled(self.update_toggle.isEnabled() and not self._update_open)
        self.bank_button.setVisible(not self._tuner_on)  # the tuner's «Salir del afinador» needs the room at 1440 px
        # the bank screen stays closable while its own write runs; it never opens over the tuner or the effects screen
        self.bank_button.setEnabled(not self._tuner_on and not self._effects_open and not self._effects_busy
                                    and not self._update_open and (self._bank_open or not self._saving))
        self.effects_action.setEnabled(self.effects_toggle.isEnabled() and not self._effects_open)
        self.catalog_panel.manage_button.setEnabled(self.effects_action.isEnabled())
        self.catalog_panel.set_install_block(self.write_block_reason() or (
            S.EFFECTS_BUSY_INSTALL if self._effects_busy or self._saving else None))
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
        shown = None if self._location is None else self._display(self._location)
        self.save_button.setToolTip(S.save_tooltip(shown, tip))
        self.save_button.setAccessibleName(S.save_button_name(shown))
        self.save_button.setAccessibleDescription(tip)
        self.dirty_label.setVisible(dirty)
        can_discard = dirty and not self._saving and not (self._tuner_on or self._effects_open or self._bank_open
                                                          or self._update_open)
        self.discard_button.setEnabled(can_discard)
        self.discard_action.setEnabled(can_discard)
        self.discard_button.setToolTip(S.discard_tooltip(DISCARD_SHORTCUT, "" if dirty else S.DISCARD_NOTHING))
        in_use = sum(1 for pt in self._patches.values() if any(not e.is_placeholder for e in pt.effects))
        self.patches_caption.setText(S.patches_caption(in_use, self._display(1), self._display(self._patch_count)))
        lacking = self._missing_by_location()
        self.missing_button.setVisible(bool(lacking))
        self.missing_button.setText(str(len(lacking)))
        tip = S.patches_missing_tip(len(lacking))
        self.missing_button.setToolTip(tip)
        self.missing_button.setAccessibleName(tip)
        self.centralWidget().update()
        self._update_library_actions()
        if self._tuner_on or self._effects_open or self._bank_open or self._update_open:  # the tuner mutes the pedal; each screen owns the window
            for w in (self.save_button, self.discard_button, self.open_file_button, self.save_file_button, self.live_check,
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
            self._clear_installed_state()
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
                                           self.effects_usage(), self._missing_by_location(), self._bank_uses())

    def _bank_uses(self) -> dict[str, int]:
        """Pedal file -> how many bank patches use it (the bank is not the pedal: it never makes an effect «in use»)."""
        uses: dict[str, int] = {}
        for entry in self.bank_store.list():
            key = f"{entry.id}:{entry.sha256}"
            if key not in self._bank_patches:
                try:
                    self._bank_patches[key] = parse_zptc(self.bank_store.read(entry.id))
                except (BankError, ValueError):
                    self._bank_patches[key] = None
            patch = self._bank_patches[key]
            files = set() if patch is None else {pedal_filename(info.filename) for slot in patch.effects
                                                 if (info := self.catalog.get(slot.effect_id)) is not None}
            for file in files:
                uses[file] = uses.get(file, 0) + 1
        return uses

    # --- «Quitar seleccionados»: one confirmation (the screen's), then one verified removal per call

    def _on_effects_remove_many(self, files: list[str]) -> None:
        reason = self.write_block_reason()
        if reason is not None:  # a pedal the app cannot edit yet: reading only
            self._report_error(reason)
            return
        if self._worker is None or not self._is_connected or self._effects_busy or not files:
            return
        names = {e.file: e.name for e in self._pedal_entries}
        self._removal = {"queue": list(files), "done": [], "names": names, "total": len(files)}
        self._remove_next()

    def _remove_next(self) -> None:
        job = self._removal
        name = job["queue"][0]
        self._set_effects_busy(True, S.EFFECTS_BUSY_REMOVE_MANY)
        self.statusBar().showMessage(S.EFFECTS_BUSY_REMOVE_MANY)
        in_use = {file: [user[0] for user in patches] for file, patches in self.effects_usage().items()}
        self._effect_remove_requested.emit(name, self.effects_backup_dir, in_use)

    def _finish_removal(self, failed: bool) -> None:
        job, self._removal = self._removal, None
        if job is None:
            return
        label = lambda files: [job["names"].get(f, f) for f in files]  # noqa: E731
        if failed:
            self._report_error(S.remove_many_stopped(label(job["done"]), label(job["queue"])))
        else:
            self.statusBar().showMessage(S.remove_many_done(len(job["done"])))

    @property
    def effects_backup_dir(self) -> Path:
        """Where the effect list is backed up before it changes."""
        if self.backup_dir is not None:
            return self.backup_dir / "effects"
        from jmc_guitar_zoom.__main__ import autosave_dir

        return autosave_dir() / "effects"

    def _on_effect_install(self, name: str, path) -> None:
        if self.write_block_reason() is not None:  # a pedal the app cannot edit yet: reading only
            self._report_error(self.write_block_reason())
            return
        if self._worker is not None and self._is_connected:
            self._set_effects_busy(True, S.EFFECTS_BUSY_INSTALL)
            self._effects_repairing = False
            self._effect_install_requested.emit(name, path, self.effects_backup_dir)

    def _open_patch_from_effects(self, location: int) -> None:
        """A patch card of the effects screen: leave the screen (through its toggle) and select that patch."""
        self.effects_toggle.setChecked(False)
        self.select_location(location)

    def _on_effect_repair(self, name: str, path) -> None:
        if self.write_block_reason() is not None:  # a pedal the app cannot edit yet: reading only
            self._report_error(self.write_block_reason())
            return
        if self._worker is not None and self._is_connected:
            self._set_effects_busy(True, S.EFFECTS_BUSY_REPAIR)
            self._effects_repairing = True  # the worker reports a repair as an install: name it right
            self._effect_repair_requested.emit(name, path, self.effects_backup_dir)

    def _on_effect_remove(self, name: str) -> None:
        if self.write_block_reason() is not None:  # a pedal the app cannot edit yet: reading only
            self._report_error(self.write_block_reason())
            return
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
        self._set_installed_state(flst_bytes, files)
        self._resume_pending_add()
        if self._removal is not None:  # the state was read again after the removal: on to the next, or done
            if self._removal["queue"]:
                self._remove_next()
            else:
                self._finish_removal(failed=False)

    def _load_installed_state(self) -> None:
        """After the patches were read: the editor needs what is installed (icons, warnings, Live, Save), a read."""
        if self._is_connected and self._worker is not None:
            self._request_effects_state()

    @Slot()
    def _on_effects_state_failed(self) -> None:
        self._clear_installed_state()
        self._pending_add = None
        if self._removal is not None:
            self._finish_removal(failed=True)

    # ----------------------------------------------- what is installed (icons, warnings, Live, save, quick install)

    def effect_installed(self, effect_id: int) -> bool | None:
        """Is the catalog effect installed on the connected pedal? ``None`` while that is not known (no state read:
        offline, not read yet, the read failed): the editor then shows no warning and blocks nothing."""
        if self._installed_ids is None:
            return None
        return effect_id in self._installed_ids

    def _compute_installed_ids(self) -> set[int] | None:
        if self._installed_files is None:
            return None
        return {i for i, info in self.catalog.items() if pedal_filename(info.filename) in self._installed_files}

    def _set_installed_state(self, flst_bytes, files) -> None:
        """Remember what the pedal reported: installed means flagged in the list *and* the file is on the pedal."""
        try:
            installed, available = build_entries(self.catalog, self.allowed_ids, flst_bytes, files)
        except flst.FlstError:
            self._clear_installed_state()
            return
        self._pedal_state = (flst_bytes, list(files))
        self._pedal_entries = installed + available
        self._installed_files = {e.file for e in installed if not e.missing}
        self._refresh_installed()

    def _clear_installed_state(self) -> None:
        self._installed_files, self._pedal_entries, self._pedal_state = None, [], None
        self._refresh_installed()

    def _refresh_installed(self) -> None:
        """The installed set changed (state read, catalog reloaded, disconnect): icons, tiles and Save follow it."""
        self._installed_ids = self._compute_installed_ids()
        self.catalog_panel.set_installed(self._installed_ids, self._installable_ids())
        patch = self.current_patch
        if patch is not None:  # the tiles carry the warning: update them in place, the parameters stay as they are
            warned = set(edit.not_installed_slots(patch, self.catalog, self._installed_ids))
            for tile in self.chain.tiles():
                tile.set_not_installed(tile.slot_index in warned)
        for location in range(1, self.patch_list.count() + 1):
            self._refresh_item(location)  # the patch cards carry the warning too
        self._refresh_bank_screen()
        self._update_buttons()

    def _installable_ids(self) -> set[int] | None:
        """Catalog effects the pedal's list can take (a flag to set, or a file to put back); ``None``: list not read."""
        if self._installed_files is None:
            return None
        by_file = {e.file: e for e in self._pedal_entries}
        return {i for i, info in self.catalog.items()
                if (e := by_file.get(pedal_filename(info.filename))) is not None and (e.installable or e.missing)}

    def _missing_effects(self) -> list[int]:
        """Catalog IDs of the effects of the current patch that are known not to be installed (each once)."""
        patch = self.current_patch
        if patch is None:
            return []
        slots = edit.not_installed_slots(patch, self.catalog, self._installed_ids)
        return list(dict.fromkeys(patch.effects[i].effect_id for i in slots))

    def _entry_for(self, effect_id: int) -> Entry | None:
        info = self.catalog.get(effect_id)
        if info is None:
            return None
        file = pedal_filename(info.filename)
        return next((e for e in self._pedal_entries if e.file == file), None)

    def quick_install(self, effect_id: int, then_add: tuple[int, int] | None = None) -> bool:
        """Install a catalog effect on the pedal without leaving the editor, through the effects screen's own path:
        its confirmation, the backup, the memory check and the write gate. ``then_add``: ``(slot, effect ID)`` to add
        once it is installed. Returns whether an install was started."""
        info = self.catalog.get(effect_id)
        name = info.name if info is not None else hex(effect_id)
        reason = self.write_block_reason()
        if reason is not None:  # a pedal the app cannot edit yet: reading only
            self._report_error(reason)
            return False
        if self._worker is None or not self._is_connected:
            self._report_error(S.INSTALL_NEEDS_PEDAL)
            return False
        if self._effects_busy or self._saving:
            return False
        entry = self._entry_for(effect_id)
        if entry is None or entry.path is None or entry.size is None or not (entry.installable or entry.missing):
            self._report_error(S.cannot_quick_install(name))
            return False
        repair = entry.missing  # flagged installed but its file is gone: only the file goes back
        if not (self.effects_panel.confirm_repair(entry, self) if repair else self.effects_panel.confirm_install(entry, self)):
            return False
        self._pending_add = None if then_add is None else (self._location, *then_add)
        self._set_effects_busy(True, S.EFFECTS_BUSY_REPAIR if repair else S.EFFECTS_BUSY_INSTALL)
        self.statusBar().showMessage(S.EFFECTS_BUSY_REPAIR if repair else S.EFFECTS_BUSY_INSTALL)
        self._effects_repairing = repair
        (self._effect_repair_requested if repair else self._effect_install_requested).emit(
            entry.file, entry.path, self.effects_backup_dir)
        return True

    def _offer_install(self, effect_id: int, reason: str, then_add: tuple[int, int] | None = None) -> None:
        """Say why an effect cannot be used and offer to install it right here."""
        if ConfirmDialog.ask(self, S.NOT_INSTALLED_TITLE, S.install_offer(reason), S.INSTALL_ON_PEDAL):
            self.quick_install(effect_id, then_add)

    def _on_tile_install(self, slot_index: int) -> None:
        patch = self.current_patch
        if patch is not None and 0 <= slot_index < len(patch.effects):
            self.quick_install(patch.effects[slot_index].effect_id)

    def _resume_pending_add(self) -> None:
        """The install that a blocked add was waiting for finished: let the add go through."""
        if self._pending_add is None:
            return
        location, slot, effect_id = self._pending_add
        if location != self._location or self.effect_installed(effect_id) is None:
            self._pending_add = None
            return
        if self.effect_installed(effect_id):
            self._pending_add = None
            self.replace_effect(slot, effect_id)

    @Slot(str, bool)
    def _on_effect_changed(self, name: str, installed: bool) -> None:
        if self._removal is not None and not installed and self._removal["queue"][:1] == [name]:
            self._removal["done"].append(self._removal["queue"].pop(0))
        if getattr(self, "_effects_repairing", False):
            message = S.effects_repaired_ok
        else:
            message = S.effects_installed_ok if installed else S.effects_removed_ok
        self.statusBar().showMessage(message(name))

    @Slot(bool)
    def _on_effect_change_finished(self, success: bool) -> None:
        self._effects_repairing = False
        if not success:
            self._pending_add = None
            if self._removal is not None:
                self._finish_removal(failed=True)
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
        self._fit_header()
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
            item.setData(ROLE_MISSING, None)
            item.setToolTip("")
            item.setData(Qt.ItemDataRole.AccessibleTextRole, item.text())
        else:
            name = patch.name or S.UNNAMED
            item.setText(f"{number}  {name}{' *' if dirty else ''}")
            item.setForeground(QBrush(self.palette().text().color()))
            item.setData(ROLE_NAME, name)
            item.setData(ROLE_STRIP, self._chain_strip(patch))
            lacking = self._missing_names(patch)  # the current chain, edited or not
            item.setData(ROLE_MISSING, lacking or None)
            item.setToolTip(S.patch_missing_tip(lacking) if lacking else "")
            item.setData(Qt.ItemDataRole.AccessibleTextRole,
                         item.text() + (f". {S.patch_missing_tip(lacking)}" if lacking else ""))

    def _missing_names(self, patch: Patch | None) -> list[str]:
        """The effects of ``patch`` known not to be installed on the connected pedal (none while that is unknown)."""
        return [] if patch is None else edit.not_installed_names(patch, self.catalog, self._installed_ids)

    def _missing_by_location(self) -> dict[int, list[str]]:
        found = {}
        for location, patch in self._patches.items():
            names = self._missing_names(patch)
            if names:
                found[location] = names
        return found

    def select_next_missing(self) -> None:
        """Select the next patch (after the current one, round again) that uses effects the pedal lacks."""
        lacking = sorted(self._missing_by_location())
        if not lacking:
            return
        after = self._location or 0
        self.select_location(next((loc for loc in lacking if loc > after), lacking[0]))

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
        self._baselines = {}

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
                             None if patch is None else edit.slot_problems(patch, self.catalog, self.allowed_ids),
                             None if patch is None else set(edit.not_installed_slots(patch, self.catalog, self._installed_ids)))
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
        """Reasons the selected patch must not be written to the pedal (the model, then A1, A2, A3 and DSP checks)."""
        patch = self.current_patch
        reasons = [] if patch is None else edit.save_blockers(patch, self.catalog, self.allowed_ids, self._installed_ids)
        block = self.write_block_reason()
        return ([block] if block else []) + reasons

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

    def discard_changes(self, location: int | None = None) -> bool:
        """Revert a patch to its last saved version as ONE undoable step («Descartar cambios»).

        The baseline is the patch as it was when its first unsaved edit began: what the app last read from the
        pedal, or last wrote and verified (SAVE, a library write, a bank load), or the file it was opened
        from. It asks first; the revert is an ordinary undo step (Ctrl+Z brings the edits back) and the
        patch is clean afterwards.

        With «En vivo» on and this patch selected on the pedal, the baseline's values (every slot's on/off and
        parameters, the name and the volume) are also sent through the live path so the pedal's edit buffer
        matches again. Nothing is ever written to pedal memory here. Note that a pedal with auto-save ON may
        already have stored the live edits, and that a live message cannot change which effect sits in a slot:
        slots whose effect changed since the baseline are not sent.
        """
        location = self._location if location is None else location
        baseline = self._baselines.get(location) if location is not None else None
        if location is None or baseline is None or not self.is_dirty(location) or self._saving:
            return False
        current = self._patches.get(location)
        if current is None:
            return False
        display = self._display(location)
        if not ConfirmDialog.ask(self, S.discard_patch_title(display, current.name),
                                 S.discard_patch_text(display, current.name), S.DISCARD_ACCEPT, danger=True):
            return False
        selected = self.chain.selected_slot if location == self._location else None
        command = PatchEdit(self, location, current, baseline, S.DISCARD_ACCEPT, None, selected, selected)
        stack = self._stack(location)
        stack.push(command)
        stack.setClean()  # the baseline is the clean state; Undo leaves it again and the patch is edited once more
        if (self.live_check.isChecked() and self._is_connected and location == self._location
                and self._live_location == location and self.write_block_reason() is None):
            for message in live_restore_messages(current, baseline):
                self._param_requested.emit(*message)
        return True

    def _push(self, after: Patch, text: str, key: tuple | None = None, select: int | None = None,
              widget: bool = False) -> None:
        location = self._location
        assert location is not None
        before = self._patches.get(location)
        if before is not None and not self.is_dirty(location):
            self._baselines[location] = copy.deepcopy(before)  # the last saved version, kept for «Descartar cambios»
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
        if self.live_check.isChecked() and self.effect_installed(effect_id) is False:
            # Live edits the pedal's own patch: an effect the pedal does not have cannot be added; offer the install
            info = self.catalog.get(effect_id)
            reason = S.live_blocks_uninstalled(info.name if info else hex(effect_id))
            self._report_error(reason)
            self._offer_install(effect_id, reason, (slot_index, effect_id))
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
                or self._live_location != self._location or self.write_block_reason() is not None):
            return  # a pedal the app cannot edit gets nothing, whatever the switch says
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
            missing = self._missing_effects()
            if missing and self.write_block_reason() is None:  # the way out is right here
                self._offer_install(missing[0], S.cannot_save(blockers))
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
        self._clear_installed_state()
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
        w.effects_state_failed.connect(self._on_effects_state_failed)
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

    # ------------------------------------------------------------- target pedal

    def _supported_pedals(self) -> list[tuple[int, str]]:
        """The pedals the app can edit that Guitar Lab describes, by name (read live: tests patch the set)."""
        return sorted(((mid, m.name) for mid, m in self.models.items() if mid in pedal_models.SUPPORTED_MODELS),
                      key=lambda pair: pair[1])

    def _initial_target(self) -> int | None:
        """The last target used when it is still supported, else the A1 FOUR, else the first supported pedal."""
        supported = {mid for mid, _name in self._supported_pedals()}
        stored = self.target_store.target
        if stored in supported:
            return stored
        if A1_FOUR in supported:
            return A1_FOUR
        return min(supported) if supported else None

    def _ids_for(self, model_id: int | None) -> set[int] | None:
        model = self.models.get(model_id) if model_id is not None else None
        return None if model is None else set(model.effect_ids) | self._extra_ids

    def _target_name(self) -> str:
        model = self.models.get(self.target_model) if self.target_model is not None else None
        return model.name if model is not None else ""

    def apply_pedal_identity(self, identity) -> None:
        """Remember which pedal is connected. A model Guitar Lab lists becomes the target, supported or not, so the
        lists and every text follow it; an unknown one leaves the last target. Only supported pedals are edited."""
        self.connected_model = model_id_from_identity(identity)
        if self.connected_model in self.models:
            self._set_target(self.connected_model)
        else:
            self._sync_effects_pedals()
        self._update_pedal_notice()

    def _pedal_supported(self) -> bool:
        return self.connected_model in pedal_models.SUPPORTED_MODELS

    def write_block_reason(self) -> str | None:
        """Why nothing may be written to the connected pedal (None: it is a supported model, or none is connected)."""
        if self.connected_model is None or self._pedal_supported():
            return None
        known = self.models.get(self.connected_model)
        return S.pedal_readonly_reason(known.name) if known is not None else S.pedal_unknown_reason()

    def _update_pedal_notice(self) -> None:
        reason = self.write_block_reason()
        known = self.models.get(self.connected_model) if self.connected_model is not None else None
        text = "" if reason is None else (S.pedal_readonly_banner(known.name) if known is not None
                                          else S.pedal_unknown_banner(self.connected_model))
        self.pedal_notice.setText(text)
        self.pedal_notice.setVisible(bool(text))
        self.effects_panel.set_write_block(reason)

    def _set_target(self, model_id: int) -> None:
        """Make ``model_id`` the pedal the editor targets: the catalog shows only what it runs; remembered."""
        if model_id != self.target_model:
            self.target_model = model_id
            self.allowed_ids = self._ids_for(model_id)
            if model_id in pedal_models.SUPPORTED_MODELS:
                self.target_store.set_target(model_id)  # only a pedal the app can edit is worth remembering
            if self._location is not None:
                self._show_patch(self._location, keep=True)  # which effects the pedal cannot run changed
        self.catalog_panel.set_pedal(self.allowed_ids, self._target_name(), self.target_model)
        self._sync_effects_pedals()

    def _apply_loaded_catalog(self, catalog: dict[int, EffectInfo], models: dict[int, PedalModel]) -> None:
        """The library changed on disk: bring the catalog and the model list up to date in place, so every screen
        that holds them (editor catalog, effects screen, chain) shows the new effects without a restart."""
        self.catalog.clear()
        self.catalog.update(catalog)
        if models:
            self.models = models
        self.allowed_ids = self._ids_for(self.target_model)
        combo = self.catalog_panel.group_combo  # the groups may have grown with the new effects
        chosen = combo.currentData()
        combo.blockSignals(True)
        while combo.count() > 2:
            combo.removeItem(2)
        for group in sorted({e.group for e in self.catalog.values()}):
            combo.addItem(S.group_label(group), group)
        index = combo.findData(chosen) if chosen is not None else 0
        combo.setCurrentIndex(max(index, 0))
        combo.blockSignals(False)
        self.catalog_panel.set_pedal(self.allowed_ids, self._target_name(), self.target_model)
        self._sync_effects_pedals()
        if self._pedal_state is not None:
            self._set_installed_state(*self._pedal_state)  # the same pedal report, read against the new catalog
        if self._location is not None:
            self._show_patch(self._location, keep=True)  # chain tiles and problems depend on the catalog

    def _sync_effects_pedals(self) -> None:
        """The effects screen installs on the connected pedal (else the target); its filter names it."""
        pedal = self.connected_model if self.connected_model in self.models else self.target_model
        self.effects_panel.set_pedals(self.models, pedal, pedal is not None and pedal == self.connected_model,
                                      self._ids_for(pedal))

    @Slot(object, object)
    def _on_connected(self, identity, info) -> None:
        self.apply_pedal_identity(identity)
        self._is_connected = True
        self._offline_dir = None
        self._patch_count = info.count
        known = self.models.get(model_id_from_identity(identity))
        model = known.name if known is not None else MODEL_NAMES.get(identity.model, S.unknown_model(identity.model))
        firmware = bytes(identity.version).decode("ascii", "replace").strip("\x00 ")
        self._set_connection(S.connected(model), True)
        self.connection_label.setToolTip(S.firmware_tip(firmware or "?"))
        self._set_pedal_firmware(firmware)
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
        self.connected_model = None
        self._set_pedal_firmware(None)
        self._pending_add = None
        self._clear_installed_state()
        self._update_pedal_notice()
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
        self._load_installed_state()
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
            memory.apply_state(self.memory_bar, self.memory_icon, self.memory_word, (self.memory_value,), None)
        else:
            pct = usage.used_percent
            self.memory_bar.setValue(round(pct))
            tip = S.memory_text(usage.used / 1024, usage.maximum / 1024, pct)
            self.memory_bar.setFormat(tip)
            self.memory_value.setText(f"{pct:.0f} %")
            memory.apply_state(self.memory_bar, self.memory_icon, self.memory_word, (self.memory_value,), usage.available)
            self._fit_header()  # the word is new content: the header may have to give a caption up
            return
        for widget in (self.memory_bar, self.memory_value):
            widget.setToolTip(tip)

    @Slot(str)
    def _report_error(self, message: str) -> None:
        self.statusBar().show_error(S.error(message), 15000)
        if self._worker is not None and not self._is_connected:
            self.connect_button.setEnabled(True)
        self.error_shown.emit(message)

    # --------------------------------------------------------------- close

    # ------------------------------------------------------------- compact header

    HEADER_LEVELS = 4  # 0: everything with its words ... 3: icons only where an icon says it

    def _set_header_level(self, level: int) -> None:
        """Words give way before anything overlaps: the caption, then the buttons' text (their tooltips stay)."""
        self._header_level = level
        self.memory_caption.setVisible(level < 1)
        self.memory_word.setVisible(level < 1 and bool(self.memory_word.text()))  # icon and % stay in a compact bar
        for button, text in ((self.tuner_button, S.TUNER),
                             (self.connect_button, S.CONNECT), (self.disconnect_button, S.DISCONNECT)):
            button.setAccessibleName(text)
        self.tuner_button.setText(S.TUNER_EXIT if self._tuner_on else ("" if level >= 2 else S.TUNER))
        self.connect_button.setText("" if level >= 3 else S.CONNECT)
        self.disconnect_button.setText("" if level >= 3 else S.DISCONNECT)
        for button, tip in ((self.connect_button, S.CONNECT), (self.disconnect_button, S.DISCONNECT)):
            button.setToolTip(tip if level >= 3 else "")

    def _fit_header(self) -> None:
        """Pick the least compact level that shows everything at its preferred width.

        When even the most compact level cannot, the lowest level whose *minimum* width fits is used: the
        connection pill then elides its text, which is better than any overlap.
        """
        header = getattr(self, "header", None)
        if header is None or getattr(self, "_fitting_header", False):
            return
        self._fitting_header = True
        try:
            fallback = None
            for level in range(self.HEADER_LEVELS):
                self._set_header_level(level)
                header.layout().invalidate()
                header.layout().activate()
                if header.layout().sizeHint().width() <= header.width():
                    return
                if fallback is None and header.layout().minimumSize().width() <= header.width():
                    fallback = level
            self._set_header_level(fallback if fallback is not None else self.HEADER_LEVELS - 1)
        finally:
            self._fitting_header = False

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        if obj is getattr(self, "header", None) and event.type() == QEvent.Type.Resize:
            self._fit_header()
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if not self._closed:
            if not self.confirm_discard(S.DISCARD_CLOSE):
                event.ignore()
                return
            self._closed = True
            self._shutdown_updates()
            if self._worker is not None and self._thread is not None:
                self._worker.cancel()
                if self._thread.isRunning():
                    # blocks until the worker finished its current request, then closes the port
                    QMetaObject.invokeMethod(self._worker, "disconnect_pedal",
                                             Qt.ConnectionType.BlockingQueuedConnection)
                self._thread.quit()
                self._thread.wait(5000)
        super().closeEvent(event)
