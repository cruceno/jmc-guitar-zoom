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

from . import strings as S
from .cards import PatchCardDelegate
from .chain import CHAIN_MIN_TILES, ChainView, EffectTile, PedalTile  # noqa: F401  (re-exported)
from .mime import MIME_EFFECT, MIME_PATCH, MIME_SLOT  # noqa: F401  (re-exported)
from .theme import group_color

ALL_GROUPS = S.ALL_GROUPS
_ID_ROLE = Qt.ItemDataRole.UserRole
_NAME_ROLE = Qt.ItemDataRole.UserRole + 1


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
        self.title = QLabel(S.SELECT_EFFECT)
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

    def clear(self, message: str = S.SELECT_EFFECT) -> None:
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
            self.title.setText(S.unknown_effect_title(slot.effect_id))
            return
        self.title.setText(f"{info.name}  -  {S.group_label(info.group)}")
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
        self.search.setPlaceholderText(S.SEARCH_EFFECTS)
        self.search.setClearButtonEnabled(True)
        self.group_combo = QComboBox()
        self.group_combo.addItem(ALL_GROUPS)
        for group in sorted({e.group for e in catalog.values()}):
            self.group_combo.addItem(S.group_label(group), group)
        self.a1_check = QCheckBox(S.ONLY_A1)
        self.a1_check.setEnabled(a1_ids is not None)
        self.list = _CatalogList()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(S.CATALOG_TITLE))
        layout.addWidget(self.search)
        layout.addWidget(self.group_combo)
        layout.addWidget(self.a1_check)
        layout.addWidget(self.list, stretch=1)
        layout.addWidget(self.preview)
        layout.addWidget(self.detail)
        self.search.textChanged.connect(self.refresh)
        self.group_combo.currentIndexChanged.connect(self.refresh)
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
        group = self.group_combo.currentData()
        if group is not None and info.group != group:
            return False
        return not (self.a1_check.isChecked() and self._a1_ids is not None
                    and info.effect_id not in self._a1_ids)

    def refresh(self) -> None:
        self.list.clear()
        for info in sorted(self._catalog.values(), key=lambda e: (e.group, e.name.lower())):
            if not self._matches(info):
                continue
            item = QListWidgetItem(S.catalog_row(info.name, info.group, info.dsp_load_percent, self._is_installed(info)))
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
        where = ", ".join(info.sources) or "-"
        self.detail.setText(S.catalog_detail(info.description, info.dsp_load_percent, info.is_wide, where))

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
