"""Main window: patch list | signal chain + parameters | effect catalog (read-only toward the pedal)."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QMetaObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QProgressBar, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.patches.model import Patch
from zoomstudio.patches.zptc import parse_zptc

from .widgets import CatalogPanel, ChainView, EffectTile, ParamPanel, ParamRow
from .worker import PedalWorker, TransportFactory

DEFAULT_PATCH_COUNT = 50
DISPLAY_OFFSET = 9  # the pedal shows locations 1..50 as 10..59
MODEL_NAMES = {0x6E: "A1 FOUR"}
_PATCH_FILE = re.compile(r"^(\d+)\.zptc$", re.IGNORECASE)
_EMPTY_COLOR = QColor("#6c6f75")


class MainWindow(QMainWindow):
    patches_loaded = Signal()  # a full read (pedal) or folder load finished
    error_shown = Signal(str)

    def __init__(self, catalog: dict[int, EffectInfo], a1_ids: set[int] | None = None,
                 transport_factory: TransportFactory | None = None, installed_label: str = "pedal",
                 pedal_timeout: float = 3.0) -> None:
        super().__init__()
        self.setWindowTitle("Zoom Studio")
        self.resize(1400, 780)
        self.catalog = catalog
        self._patches: dict[int, Patch] = {}
        self._dirty: set[int] = set()
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
        h.addWidget(self.connection_label)
        h.addWidget(self.memory_bar)
        h.addStretch(1)
        for b in (self.connect_button, self.disconnect_button, self.open_button, self.reload_button):
            h.addWidget(b)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.disconnect_button.clicked.connect(self._on_disconnect_clicked)
        self.open_button.clicked.connect(self._choose_folder)
        self.reload_button.clicked.connect(self.reload)

        self.patch_list = QListWidget()
        self.patch_list.currentRowChanged.connect(self._on_row_changed)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Patches"))
        lv.addWidget(self.patch_list)

        self.patch_title = QLabel("No patch selected")
        self.patch_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.chain = ChainView()
        self.params = ParamPanel()
        centre = QWidget()
        cv = QVBoxLayout(centre)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(self.patch_title)
        cv.addWidget(self.chain)
        cv.addWidget(self.params, stretch=1)
        self.chain.tile_selected.connect(self._on_tile_selected)
        self.chain.power_toggled.connect(self._on_power_toggled)
        self.params.param_changed.connect(self._on_param_changed)

        self.catalog_panel = CatalogPanel(self.catalog, a1_ids, installed_label)

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
        self.statusBar().showMessage("Ready")

    def _update_buttons(self) -> None:
        can_connect = self._worker is not None
        self.connect_button.setEnabled(can_connect and not self._is_connected)
        self.disconnect_button.setEnabled(self._is_connected)
        self.reload_button.setEnabled(self._is_connected or self._offline_dir is not None)

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
        self.chain.clear()
        self.params.clear()
        self.patch_title.setText("No patch selected")

    def is_empty_slot(self, location: int) -> bool:
        return location not in self._patches

    def is_dirty(self, location: int) -> bool:
        return location in self._dirty

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
            item.setText(f"{number}  {name}{' *' if location in self._dirty else ''}")
            item.setForeground(QBrush(self.palette().text().color()))

    def _set_patch(self, location: int, patch: Patch) -> None:
        self._patches[location] = patch
        self._dirty.discard(location)
        self._refresh_item(location)
        if location == self._location:
            self._show_patch(location)

    def select_location(self, location: int) -> None:
        self.patch_list.setCurrentRow(location - 1)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        self._show_patch(row + 1)

    def _show_patch(self, location: int) -> None:
        self._location = location
        patch = self._patches.get(location)
        self.chain.set_patch(patch, self.catalog)
        self.params.clear()
        if patch is None:
            self.patch_title.setText(f"{self._display(location)}  -  empty")
            return
        self.patch_title.setText(f"{self._display(location)}  {patch.name}  (volume {patch.volume})")
        real = [t for t in self.chain.tiles() if not t.is_empty]
        if real:
            self.select_tile(real[0].slot_index)

    # --------------------------------------------------------- chain/params

    def chain_tiles(self) -> list[EffectTile]:
        return self.chain.tiles()

    def param_rows(self) -> list[ParamRow]:
        return self.params.rows()

    def select_tile(self, slot_index: int) -> None:
        self.chain.select(slot_index)

    def _on_tile_selected(self, slot_index: int) -> None:
        patch = self.current_patch
        if patch is None or slot_index >= len(patch.effects):
            return
        slot = patch.effects[slot_index]
        self.params.show_effect(slot, self.catalog.get(slot.effect_id))

    def _mark_dirty(self) -> None:
        if self._location is not None:
            self._dirty.add(self._location)
            self._refresh_item(self._location)

    def _on_param_changed(self, index: int, value: int) -> None:
        patch, slot_index = self.current_patch, self.chain.selected_slot
        if patch is None or slot_index is None:
            return
        patch.effects[slot_index].params[index] = value
        self._mark_dirty()

    def _on_power_toggled(self, slot_index: int, on: bool) -> None:
        patch = self.current_patch
        if patch is None:
            return
        patch.effects[slot_index].enabled = on
        self._mark_dirty()

    # ------------------------------------------------------------- offline

    def _choose_folder(self) -> None:
        start = str(self._offline_dir or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Open patch backup folder", start)
        if folder:
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
        self._patches, self._dirty = {}, set()
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
        if self._is_connected and self._worker is not None:
            self._begin_pedal_read()
        elif self._offline_dir is not None:
            self.load_offline(self._offline_dir)
        else:
            self.statusBar().showMessage("Nothing to reload: connect or open a folder first")

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
        w.error.connect(self._report_error)
        self._thread.start()

    def start_connect(self) -> None:
        """Begin connecting to the pedal (no-op without a transport factory)."""
        if self._worker is None or self._is_connected:
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
        self._patches, self._dirty = {}, set()
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
