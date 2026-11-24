"""Building blocks of the main window: chain tiles, parameter knobs, effect catalog."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDial, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from zoomstudio.effects.catalog import EffectInfo
from zoomstudio.patches.model import EffectSlot, Patch

from .theme import group_color

ALL_GROUPS = "All groups"
MIME_EFFECT = "application/x-zoomstudio-effect"  # payload: catalog effect ID (decimal text)
MIME_SLOT = "application/x-zoomstudio-slot"  # payload: slot index of a chain tile (decimal text)
MIME_PATCH = "application/x-zoomstudio-patch"  # payload: location of a patch in the list (decimal text)
CHAIN_MIN_TILES = 5  # the chain view always offers at least this many effect positions
_ID_ROLE = Qt.ItemDataRole.UserRole
_NAME_ROLE = Qt.ItemDataRole.UserRole + 1


class EffectTile(QFrame):
    """One effect of the chain (or an empty slot). ``span`` is the number of chain slots it covers."""

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
        if slot.is_empty:
            self.effect_name = ""
        else:
            self.effect_name = info.name if info else f"0x{slot.effect_id:08X}"
        label = ("! " + self.effect_name) if problem else self.effect_name
        self.setObjectName("tile")
        self.setMinimumHeight(110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)
        self._press_pos = None
        self._color = group_color(self.group) if info else QColor("#555a62")
        layout = QVBoxLayout(self)
        self.name_label = QLabel(label or "empty")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.name_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self.name_label.setFont(font)
        self.group_label = QLabel(self.group.title() if not slot.is_empty else "")
        self.group_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.power = QToolButton()
        self.power.setCheckable(True)
        self.power.setChecked(slot.enabled)
        self._sync_power_text()
        self.power.setVisible(not slot.is_empty)
        self.power.toggled.connect(self._on_power)
        layout.addWidget(self.name_label)
        layout.addWidget(self.group_label)
        layout.addStretch(1)
        layout.addWidget(self.power, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.remove_button = QToolButton(self)
        self.remove_button.setText("x")
        self.remove_button.setToolTip("Remove this effect")
        self.remove_button.setAutoRaise(True)
        self.remove_button.setVisible(not slot.is_empty)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.slot_index))
        self.remove_button.setFixedSize(20, 20)
        self.remove_button.move(4, 4)
        self.remove_button.raise_()
        if slot.is_empty:
            self.setToolTip("Empty slot")
        elif info:
            self.setToolTip(f"{info.name} ({info.group}) - {info.dsp_load_percent:.1f}% DSP"
                            + (" - occupies two slots" if self.is_wide else ""))
        if problem:
            self.setToolTip(f"Cannot be written to the pedal: {problem}\n" + self.toolTip())
        self.set_selected(False)

    def _sync_power_text(self) -> None:
        self.power.setText("ON" if self.power.isChecked() else "OFF")

    def _on_power(self, on: bool) -> None:
        self.is_enabled_effect = on
        self._sync_power_text()
        self._restyle(self._selected)
        self.power_toggled.emit(self.slot_index, on)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._restyle(selected)

    def _restyle(self, selected: bool) -> None:
        if self.is_empty:
            bg, border, style = "#25272b", "#4a4d54", "dashed"
        else:
            base = self._color if self.is_enabled_effect else QColor("#44474d")
            bg, border, style = base.darker(160 if self.is_enabled_effect else 110).name(), base.name(), "solid"
        if self.problem and not self.is_empty:
            bg, border, style = "#4a1f1f", "#e5533d", "solid"
        if selected:
            border = "#ffffff"
        self.setStyleSheet(
            f"#tile {{ background: {bg}; border: 2px {style} {border}; border-radius: 8px; }}"
            "#tile QLabel { background: transparent; }"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._press_pos = event.position().toPoint()
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
        drag.setPixmap(self.grab())
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


class ChainView(QWidget):
    """Signal chain of the selected patch as a row of tiles."""

    tile_selected = Signal(int)
    power_toggled = Signal(int, bool)
    remove_requested = Signal(int)
    effect_dropped = Signal(int, int)
    tile_moved = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._tiles: list[EffectTile] = []
        self._selected: int | None = None

    def tiles(self) -> list[EffectTile]:
        return list(self._tiles)

    def clear(self) -> None:
        for tile in self._tiles:
            self._layout.removeWidget(tile)
            tile.setParent(None)  # leave the window now; deleteLater alone keeps painting it
            tile.deleteLater()
        self._tiles = []
        self._selected = None

    def set_patch(self, patch: Patch | None, catalog: dict[int, EffectInfo],
                  problems: dict[int, str] | None = None) -> None:
        self.clear()
        if patch is None:
            return
        slots = patch.effects
        for i, slot in enumerate(slots):
            if slot.is_wide_filler:
                continue  # drawn as the second half of the wide tile before it
            info = catalog.get(slot.effect_id)
            followed_by_filler = i + 1 < len(slots) and slots[i + 1].is_wide_filler
            wide = not slot.is_empty and (followed_by_filler or (info is not None and info.is_wide))
            tile = EffectTile(i, slot, info, 2 if wide else 1, (problems or {}).get(i, ""))
            self._add_tile(tile)
        for k in range(max(0, CHAIN_MIN_TILES - len(self._tiles))):
            # empty drop targets beyond the stored chain (slot indexes past the end of the patch)
            self._add_tile(EffectTile(len(slots) + k, EffectSlot(), None, 1))

    def _add_tile(self, tile: EffectTile) -> None:
        tile.clicked.connect(self.select)
        tile.power_toggled.connect(self.power_toggled)
        tile.remove_requested.connect(self.remove_requested)
        tile.effect_dropped.connect(self.effect_dropped)
        tile.tile_dropped.connect(self.tile_moved)
        self._layout.addWidget(tile, stretch=tile.span)
        self._tiles.append(tile)

    def select(self, slot_index: int | None) -> None:
        self._selected = slot_index
        for tile in self._tiles:
            tile.set_selected(tile.slot_index == slot_index)
        if slot_index is not None:
            self.tile_selected.emit(slot_index)

    @property
    def selected_slot(self) -> int | None:
        return self._selected


class PatchList(QListWidget):
    """Patch list whose rows can be dragged onto each other (a swap request, never a move)."""

    patch_dropped = Signal(int, int)  # source location, target location

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.IgnoreAction)

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
    """Knob and value box for one effect parameter."""

    changed = Signal(int, int)  # parameter index, new value

    def __init__(self, index: int, name: str, maximum: int, default: int, value: int, tooltip: str = "") -> None:
        super().__init__()
        self.index = index
        self.name = name
        self.default = default
        maximum = max(maximum, value)  # never hide a stored value that exceeds the catalog range
        self.dial = QDial()
        self.dial.setRange(0, maximum)
        self.dial.setNotchesVisible(maximum <= 20)
        self.dial.setFixedSize(QSize(64, 64))
        self.spin = QSpinBox()
        self.spin.setRange(0, maximum)
        self.dial.setValue(value)
        self.spin.setValue(value)
        self.label = QLabel(name)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.label)
        layout.addWidget(self.dial, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.spin)
        if tooltip:
            self.setToolTip(tooltip)
        self.dial.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.dial.setValue)
        self.spin.valueChanged.connect(lambda v: self.changed.emit(self.index, v))
        self.dial.mouseDoubleClickEvent = lambda _e: self.spin.setValue(self.default)  # type: ignore[method-assign]


class ParamPanel(QWidget):
    """Knobs for the parameters of the selected effect."""

    param_changed = Signal(int, int)  # parameter index, value

    COLUMNS = 6

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("Select an effect in the chain")
        self.title.setStyleSheet("font-weight: bold;")
        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.description.setStyleSheet("color: #9a9da3;")
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.title)
        outer.addWidget(self.description)
        outer.addWidget(self._grid_host)
        outer.addStretch(1)
        self._rows: list[ParamRow] = []

    def rows(self) -> list[ParamRow]:
        return list(self._rows)

    def clear(self, message: str = "Select an effect in the chain") -> None:
        for row in self._rows:
            self._grid.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        self.title.setText(message)
        self.description.setText("")

    def show_effect(self, slot: EffectSlot, info: EffectInfo | None) -> None:
        self.clear()
        if info is None:
            self.title.setText(f"Effect 0x{slot.effect_id:08X} is not in the catalog (no parameter ranges)")
            return
        self.title.setText(f"{info.name}  -  {info.group.title()}")
        self.description.setText(info.description)
        for i, param in enumerate(info.params[: len(slot.params)]):
            row = ParamRow(i, param.name, param.max, param.default, slot.params[i], param.explanation)
            row.changed.connect(self.param_changed)
            self._grid.addWidget(row, i // self.COLUMNS, i % self.COLUMNS)
            self._rows.append(row)


class _CatalogList(QListWidget):
    """Catalog rows that can be dragged onto a chain tile (payload: the effect ID)."""

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)

    def mimeData(self, items) -> QMimeData:  # noqa: N802 (Qt API)
        mime = QMimeData()
        if items:
            mime.setData(MIME_EFFECT, QByteArray(str(items[0].data(_ID_ROLE)).encode()))
        return mime


class CatalogPanel(QWidget):
    """Searchable effect catalog with group and A1 FOUR filters, DSP load and an SVG preview."""

    effect_activated = Signal(int)  # double click on a row: catalog effect ID

    def __init__(self, catalog: dict[int, EffectInfo], a1_ids: set[int] | None, installed_label: str) -> None:
        super().__init__()
        self._catalog = catalog
        self._a1_ids = a1_ids
        self._installed_label = installed_label
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search effects...")
        self.search.setClearButtonEnabled(True)
        self.group_combo = QComboBox()
        self.group_combo.addItem(ALL_GROUPS)
        self.group_combo.addItems(sorted({e.group for e in catalog.values()}))
        self.a1_check = QCheckBox("A1 FOUR compatible")
        self.a1_check.setEnabled(a1_ids is not None)
        self.list = _CatalogList()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Effect catalog"))
        layout.addWidget(self.search)
        layout.addWidget(self.group_combo)
        layout.addWidget(self.a1_check)
        layout.addWidget(self.list, stretch=1)
        layout.addWidget(self.preview)
        layout.addWidget(self.detail)
        self.search.textChanged.connect(self.refresh)
        self.group_combo.currentTextChanged.connect(self.refresh)
        self.a1_check.toggled.connect(self.refresh)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemDoubleClicked.connect(lambda item: self.effect_activated.emit(item.data(_ID_ROLE)))
        self.refresh()

    def _is_installed(self, info: EffectInfo) -> bool:
        return self._installed_label in info.sources

    def _matches(self, info: EffectInfo) -> bool:
        text = self.search.text().strip().lower()
        if text and text not in info.name.lower() and text not in info.group.lower():
            return False
        group = self.group_combo.currentText()
        if group != ALL_GROUPS and info.group != group:
            return False
        return not (self.a1_check.isChecked() and self._a1_ids is not None
                    and info.effect_id not in self._a1_ids)

    def refresh(self) -> None:
        self.list.clear()
        for info in sorted(self._catalog.values(), key=lambda e: (e.group, e.name.lower())):
            if not self._matches(info):
                continue
            flag = "  [on pedal]" if self._is_installed(info) else ""
            item = QListWidgetItem(f"{info.name}   {info.group.title()}   {info.dsp_load_percent:.1f}%{flag}")
            item.setData(_ID_ROLE, info.effect_id)
            item.setData(_NAME_ROLE, info.name)
            item.setForeground(group_color(info.group).lighter(150))
            self.list.addItem(item)

    def visible_names(self) -> list[str]:
        return [self.list.item(i).data(_NAME_ROLE) for i in range(self.list.count())]

    def _on_current(self, item: QListWidgetItem | None, _prev=None) -> None:
        self.preview.clear()
        self.detail.setText("")
        if item is None:
            return
        info = self._catalog[item.data(_ID_ROLE)]
        if info.svg_path is not None:
            pixmap = render_svg(info.svg_path, 220)
            if pixmap is not None:
                self.preview.setPixmap(pixmap)
        slots = "2 slots" if info.is_wide else "1 slot"
        where = ", ".join(info.sources) or "-"
        self.detail.setText(f"{info.description}\n{info.dsp_load_percent:.1f}% DSP, {slots}. In: {where}")

    def preview_has_image(self) -> bool:
        pixmap = self.preview.pixmap()
        return pixmap is not None and not pixmap.isNull()


def render_svg(path, width: int) -> QPixmap | None:
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    size = renderer.defaultSize()
    if size.isEmpty():
        return None
    height = max(1, round(width * size.height() / size.width()))
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return QPixmap.fromImage(image)
