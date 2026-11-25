"""The "Biblioteca de efectos" update view and the window-side machinery behind it.

``UpdateView`` only shows and asks: the new and the updated effects as cards, «Todos los modelos», «Descargar» with
progress and «Cancelar», and a summary. ``UpdateMixin`` decides: it runs the library updater on its own thread (never
the pedal's worker), throttles the start-up check to once a day, shows the calm status-bar notice, and reloads the
catalog in place after a download. Nothing here touches the pedal or opens a MIDI port.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSizePolicy, QStyle,
    QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
)

from zoomstudio.library import updater as lib_updater
from zoomstudio.library.updater import CheckResult, DownloadReport, EffectUpdate, LibraryUpdater

from . import strings as S
from . import tokens
from .cards import card_path, with_alpha
from .fonts import display_font, ui_font
from .glass import BackdropRoot, GlassPanel
from .icons import icon
from .painted import SectionLabel
from .theme import group_color, group_fill_color, group_text_color

ROLE_UPDATE = Qt.ItemDataRole.UserRole + 50  # the EffectUpdate behind a card
CARD_HEIGHT = 60
SHOWN_FAILURES = 4


def system_online() -> bool:
    """False only when the system positively reports no connection; unknown counts as online."""
    try:
        from PySide6.QtNetwork import QNetworkInformation

        if QNetworkInformation.loadDefaultBackend() or QNetworkInformation.instance() is not None:
            info = QNetworkInformation.instance()
            return info is None or info.reachability() != QNetworkInformation.Reachability.Disconnected
    except Exception:  # noqa: BLE001 - no backend on this platform: try the network and let a failure be quiet
        pass
    return True


class UpdateCard(QStyledItemDelegate):
    """An effect the channel offers: group monogram, name, then group, version (old → new) and size when known."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt API)
        return QSize(1, CARD_HEIGHT)

    def paint(self, p: QPainter, option, index) -> None:
        item: EffectUpdate = index.data(ROLE_UPDATE)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 3, -2, -3)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0, tokens.color("card-hover" if hover else "card-top"))
        fill.setColorAt(1, tokens.color("card-bottom"))
        path = card_path(rect)
        p.fillPath(path, fill)
        p.setPen(QPen(tokens.color("card-rim"), 1))
        p.drawPath(path)
        mono = QRectF(rect.left() + 10, rect.center().y() - 21, 30, 42)
        p.setBrush(group_fill_color(item.group or item.name))
        p.setPen(QPen(group_color(item.group or item.name), 1.5))
        p.drawRoundedRect(mono, 7, 7)
        p.setPen(group_text_color(item.group or item.name))
        p.setFont(display_font(12, 600))
        p.drawText(mono, Qt.AlignmentFlag.AlignCenter, item.name[:2].upper())
        left, right = mono.right() + 12, rect.right() - 12
        p.setFont(ui_font(15))
        p.setPen(tokens.color("text-primary"))
        name_rect = QRectF(left, rect.top() + 6, right - left, 20)
        p.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter, QFontMetrics(ui_font(15)).elidedText(
            item.name, Qt.TextElideMode.ElideRight, int(name_rect.width())))
        p.setFont(ui_font(12))
        p.setPen(tokens.color("text-secondary"))
        line = QRectF(left, rect.top() + 29, right - left, 18)
        p.drawText(line, Qt.AlignmentFlag.AlignVCenter, QFontMetrics(ui_font(12)).elidedText(
            S.update_card_line(item.group, item.version, item.local_version, item.size),
            Qt.TextElideMode.ElideRight, int(line.width())))
        p.restore()


class _Cards(QListWidget):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.setItemDelegate(UpdateCard(self))
        self.setAccessibleName(name)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class UpdateView(GlassPanel):
    """What the channel offers, in two lists, with the download controls and what happened."""

    close_requested = Signal()
    check_requested = Signal(bool)  # the «Todos los modelos» state
    download_requested = Signal(object)  # the EffectUpdate list shown
    cancel_requested = Signal()
    state_shown = Signal()

    def __init__(self, root: BackdropRoot) -> None:
        super().__init__(root)
        self._pending: list[EffectUpdate] = []
        self._busy = False
        self._checking = False

        self.close_button = QPushButton(S.UPDATE_CLOSE)
        self.close_button.setIcon(icon("x"))
        self.close_button.clicked.connect(self.close_requested)
        self.scope_label = QLabel("")
        self.scope_label.setProperty("role", "secondary")
        self.all_models = QCheckBox(S.UPDATE_ALL_MODELS)
        self.all_models.setToolTip(S.UPDATE_ALL_MODELS_TIP)
        self.all_models.toggled.connect(lambda on: self.check_requested.emit(on))
        self.check_button = QPushButton(S.UPDATE_CHECK)
        self.check_button.setIcon(icon("reload"))
        self.check_button.setToolTip(S.UPDATE_CHECK_TIP)
        self.check_button.clicked.connect(lambda: self.check_requested.emit(self.all_models.isChecked()))
        self.firmware_label = QLabel("")
        self.firmware_label.setProperty("role", "notice")
        self.firmware_label.setWordWrap(True)
        self.firmware_label.hide()

        self.new_list, self.new_count, self.new_empty = _Cards(S.UPDATE_NEW_LIST_NAME), QLabel(""), QLabel(S.UPDATE_NO_NEW)
        self.updated_list, self.updated_count, self.updated_empty = (
            _Cards(S.UPDATE_UPDATED_LIST_NAME), QLabel(""), QLabel(S.UPDATE_NO_UPDATED))
        for empty in (self.new_empty, self.updated_empty):
            empty.setProperty("role", "secondary")
            empty.setWordWrap(True)
        for count in (self.new_count, self.updated_count):
            count.setProperty("role", "secondary")

        self.message_label = QLabel("")
        self.message_label.setProperty("role", "offline")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setAccessibleName(S.UPDATE_PROGRESS_LIST)
        self.progress_bar.setTextVisible(False)  # the count is a label: text over a thin bar cannot be read
        self.progress_bar.setMaximumWidth(320)
        self.progress_label = QLabel("")
        self.progress_label.setProperty("role", "secondary")
        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "strong")
        self.summary_label.setWordWrap(True)
        self.failures_label = QLabel("")
        self.failures_label.setProperty("role", "reason")
        self.failures_label.setProperty("blocking", True)
        self.failures_label.setAccessibleName(S.UPDATE_SUMMARY_FAILED_LIST)
        self.failures_label.setWordWrap(True)
        self.folder_label = QLabel("")
        self.folder_label.setProperty("role", "secondary")
        self.folder_label.setWordWrap(True)
        self.download_button = QPushButton(S.UPDATE_DOWNLOAD)
        self.download_button.setProperty("primary", True)
        self.download_button.setIcon(icon("arrowDown", "on-accent"))
        self.download_button.setToolTip(S.UPDATE_DOWNLOAD_TIP)
        self.download_button.clicked.connect(lambda: self.download_requested.emit(list(self._pending)))
        self.cancel_button = QPushButton(S.UPDATE_CANCEL)
        self.cancel_button.setToolTip(S.UPDATE_CANCEL_TIP)
        self.cancel_button.clicked.connect(self.cancel_requested)

        title = QHBoxLayout()
        title.addWidget(SectionLabel(S.UPDATE_TITLE))
        title.addStretch(1)
        title.addWidget(self.close_button)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(self.scope_label, stretch=1)
        controls.addWidget(self.all_models)
        controls.addWidget(self.check_button)

        self.content = QWidget()
        columns = QHBoxLayout(self.content)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(14)
        columns.addLayout(self._column(S.UPDATE_NEW_TITLE, self.new_count, self.new_empty, self.new_list))
        columns.addLayout(self._column(S.UPDATE_UPDATED_TITLE, self.updated_count, self.updated_empty, self.updated_list))
        self.message_box = QWidget()
        box = QVBoxLayout(self.message_box)
        box.addStretch(1)
        box.addWidget(self.message_label)
        box.addStretch(1)

        progress = QHBoxLayout()
        progress.setSpacing(12)
        progress.addWidget(self.progress_bar)
        progress.addWidget(self.progress_label)
        progress.addStretch(1)
        progress.addWidget(self.cancel_button)
        progress.addWidget(self.download_button)
        self.progress_row = QWidget()
        self.progress_row.setLayout(progress)
        progress.setContentsMargins(0, 0, 0, 0)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(12)
        lay.addLayout(title)
        lay.addLayout(controls)
        lay.addWidget(self.firmware_label)
        lay.addWidget(self.content, stretch=1)
        lay.addWidget(self.message_box, stretch=1)
        lay.addWidget(self.summary_label)
        lay.addWidget(self.failures_label)
        lay.addWidget(self.folder_label)
        lay.addWidget(self.progress_row)
        self.set_idle()

    @staticmethod
    def _column(title: str, count: QLabel, empty: QLabel, cards: QListWidget) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(SectionLabel(title))
        head.addStretch(1)
        head.addWidget(count)
        col.addLayout(head)
        col.addWidget(cards, stretch=1)
        col.addWidget(empty)
        return col

    # ------------------------------------------------------------ states

    def _show_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.content.hide()
        self.message_box.show()

    def _show_lists(self) -> None:
        self.message_box.hide()
        self.content.show()

    def _update_controls(self) -> None:
        idle = not self._busy and not self._checking
        self.check_button.setEnabled(idle)
        self.all_models.setEnabled(idle)
        self.download_button.setEnabled(idle and bool(self._pending))
        self.cancel_button.setVisible(self._busy)
        self.download_button.setVisible(not self._busy)
        self.progress_bar.setVisible(self._busy)
        self.progress_label.setVisible(self._busy)
        self.progress_row.setVisible(self._busy or bool(self._pending) or self._checking)

    def set_idle(self) -> None:
        """Nothing asked yet."""
        self._pending, self._busy, self._checking = [], False, False
        self.summary_label.hide()
        self.failures_label.hide()
        self.folder_label.hide()
        self.firmware_label.hide()
        self._show_message("")
        self._update_controls()

    def set_scope(self, pedal: str) -> None:
        self.scope_label.setText(S.update_scope(pedal, self.all_models.isChecked()))

    def set_checking(self) -> None:
        self._checking = True
        self._pending = []
        self.summary_label.hide()
        self.failures_label.hide()
        self._show_message(S.UPDATE_CHECKING)
        self._update_controls()

    def set_error(self, text: str) -> None:
        self._checking = False
        self._pending = []
        self.firmware_label.hide()
        self._show_message(text)
        self._update_controls()
        self.state_shown.emit()

    def set_result(self, result: CheckResult, firmware_text: str = "", folder: object = "") -> None:
        self._checking = False
        self._pending = result.pending
        self._fill(self.new_list, self.new_count, self.new_empty, result.new)
        self._fill(self.updated_list, self.updated_count, self.updated_empty, result.updated)
        self.firmware_label.setText(firmware_text)
        self.firmware_label.setVisible(bool(firmware_text))
        self.folder_label.setText(S.update_library_folder(folder) if folder and self._pending else "")
        self.folder_label.setVisible(bool(self.folder_label.text()))
        if self._pending:
            self._show_lists()
        else:
            self._show_message(S.UPDATE_UP_TO_DATE)
        self._update_controls()
        self.state_shown.emit()

    @staticmethod
    def _fill(cards: QListWidget, count: QLabel, empty: QLabel, items: list[EffectUpdate]) -> None:
        cards.clear()
        for entry in items:
            row = QListWidgetItem()
            row.setData(ROLE_UPDATE, entry)
            row.setFlags(Qt.ItemFlag.ItemIsEnabled)
            cards.addItem(row)
        count.setText(S.update_count(len(items)) if items else "")
        empty.setVisible(not items)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.summary_label.hide()
            self.failures_label.hide()
            self.progress_bar.setRange(0, max(1, len(self._pending)))
            self.progress_bar.setValue(0)
        self._update_controls()

    def set_progress(self, done: int, total: int, name: str) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        self.progress_label.setText(S.update_progress(done, total, name))

    def set_summary(self, report: DownloadReport) -> None:
        """What happened; what was downloaded leaves the lists, what failed stays to try again."""
        self._busy = False
        done = {r.entry.effect_id for r in report.results if r.ok}
        self._pending = [e for e in self._pending if e.effect_id not in done]
        self._fill(self.new_list, self.new_count, self.new_empty, [e for e in self._pending if e.kind == "new"])
        self._fill(self.updated_list, self.updated_count, self.updated_empty,
                   [e for e in self._pending if e.kind == "updated"])
        self.summary_label.setText(S.update_summary(report.ok_count, report.failed_count, report.cancelled))
        self.summary_label.show()
        failed = [r for r in report.results if not r.ok]
        lines = [S.update_failure(r.entry.name, r.reason or "") for r in failed[:SHOWN_FAILURES]]
        if len(failed) > SHOWN_FAILURES:
            lines.append(S.update_more_failures(len(failed) - SHOWN_FAILURES))
        self.failures_label.setText("\n".join(lines))
        self.failures_label.setVisible(bool(lines))
        self.folder_label.hide()
        if self._pending:
            self._show_lists()
        else:
            self._show_message(S.UPDATE_UP_TO_DATE)
        self._update_controls()
        self.state_shown.emit()

    # ------------------------------------------------------------ for tests and the window

    def new_names(self) -> list[str]:
        return [self.new_list.item(i).data(ROLE_UPDATE).name for i in range(self.new_list.count())]

    def updated_names(self) -> list[str]:
        return [self.updated_list.item(i).data(ROLE_UPDATE).name for i in range(self.updated_list.count())]

    def message(self) -> str:
        return "" if self.message_box.isHidden() else self.message_label.text()

    def pending(self) -> list[EffectUpdate]:
        return list(self._pending)


class ElidedLabel(QLabel):
    """A one-line label that elides its text to the room it gets and keeps the whole text as its tooltip."""

    def __init__(self) -> None:
        super().__init__("")
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def _elide(self) -> None:
        width = max(self.width() - 2 * self.margin(), 0)
        self.setText(QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, width)
                     if width else self._full)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._elide()


class UpdateWorker(QObject):
    """Runs the updater on its own thread; the pedal's worker is never involved. Signals carry results only."""

    check_done = Signal(object, str, bool, bool)  # CheckResult | None, error text, background, all models
    progress = Signal(int, int, str)
    download_done = Signal(object, object, str)  # DownloadReport | None, (catalog, models) | None, error text

    def __init__(self, updater: LibraryUpdater, loader: Callable[[], tuple] | None) -> None:
        super().__init__()
        self._updater = updater
        self._loader = loader
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()  # thread-safe: read between two downloads

    @Slot(object, bool, object, bool)
    def check(self, model_id, all_models: bool, firmware, background: bool) -> None:
        try:
            result = self._updater.check(model_id=model_id, all_models=all_models, firmware=firmware)
            self.check_done.emit(result, "", background, all_models)
        except lib_updater.UpdateError as exc:
            self.check_done.emit(None, str(exc), background, all_models)
        except Exception as exc:  # noqa: BLE001 - whatever happened, the window gets a message and no crash
            self.check_done.emit(None, str(exc), background, all_models)

    @Slot(object)
    def download(self, entries) -> None:
        self._cancel.clear()
        try:
            report = self._updater.download(
                entries, progress=lambda done, total, item: self.progress.emit(done, total, item.name),
                cancelled=self._cancel.is_set)
        except Exception as exc:  # noqa: BLE001
            self.download_done.emit(None, None, str(exc))
            return
        loaded = None
        if report.ok_count and self._loader is not None:
            try:
                loaded = self._loader()
            except Exception:  # noqa: BLE001 - the files are saved; the next start loads them
                loaded = None
        self.download_done.emit(report, loaded, "")


class UpdateMixin:
    """Mixed into ``MainWindow``; relies on its signals, catalog panels, status bar and button state."""

    def _init_updates(self, updater: LibraryUpdater | None, reload_sources, store, online, clock) -> None:
        from . import settings as settings_module

        self._updater = updater
        self._reload_sources = reload_sources
        self._update_store = store if store is not None else settings_module.UpdateStore(settings_module.update_path())
        self._online = online if online is not None else system_online
        self._update_clock = clock if clock is not None else time.time
        self._update_open = False
        self._update_busy = False
        self._update_worker: UpdateWorker | None = None
        self._update_thread: QThread | None = None
        self._update_pending = 0  # effects the channel has for the target pedal that the library lacks
        self._remote_firmware: dict[int, str] = {}
        self._firmware_updates: set[int] = set()
        self._pedal_firmware: str | None = None  # the connected pedal's version
        self._notice_dismissed = False

    # ------------------------------------------------------------ UI

    def _build_update_panel(self, backdrop_root: BackdropRoot) -> UpdateView:
        panel = UpdateView(backdrop_root)
        panel.hide()
        panel.close_requested.connect(lambda: self.update_toggle.setChecked(False))
        panel.check_requested.connect(self._request_update_check)
        panel.download_requested.connect(self._start_update_download)
        panel.cancel_requested.connect(self._cancel_update_download)
        return panel

    def _build_update_ui(self) -> None:
        """The Biblioteca menu entry and the calm notice at the right of the status bar."""
        self.update_action = QAction(S.LIBRARY_UPDATE, self)
        self.update_action.setIcon(icon("reload"))
        self.update_action.triggered.connect(lambda _c=False: self.open_update_view())
        menu = self.library_button.menu()
        actions = menu.actions()
        anchor = actions.index(self.backup_action) - 1  # the separator before the backup entries
        menu.insertAction(actions[anchor], self.update_action)
        self.update_notice = ElidedLabel()
        self.update_notice.setProperty("role", "secondary")
        self.update_notice.hide()
        self.update_notice_button = QPushButton(S.UPDATE_NOTICE_VIEW)
        self.update_notice_button.setToolTip(S.UPDATE_NOTICE_VIEW_TIP)
        self.update_notice_button.clicked.connect(self.open_update_view)
        self.update_notice_button.hide()
        self.update_notice_dismiss = QToolButton()
        self.update_notice_dismiss.setIcon(icon("x", "text-secondary", 16))
        self.update_notice_dismiss.setToolTip(S.UPDATE_NOTICE_DISMISS)
        self.update_notice_dismiss.setAccessibleName(S.UPDATE_NOTICE_DISMISS)
        self.update_notice_dismiss.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.update_notice_dismiss.clicked.connect(self._dismiss_update_notice)
        self.update_notice_dismiss.hide()
        bar = self.statusBar()
        bar.addPermanentWidget(self.update_notice, 1)
        bar.addPermanentWidget(self.update_notice_button)
        bar.addPermanentWidget(self.update_notice_dismiss)

    # ------------------------------------------------------------ which pedal

    def _update_model(self) -> int | None:
        """The pedal the check is about: the connected one when Guitar Lab lists it, else the target."""
        return self.connected_model if self.connected_model in self.models else self.target_model

    def _update_pedal_name(self) -> str:
        known = self.models.get(self._update_model()) if self._update_model() is not None else None
        return known.name if known is not None else ""

    # ------------------------------------------------------------ worker

    def _ensure_update_worker(self) -> UpdateWorker:
        if self._update_worker is None:
            self._update_worker = UpdateWorker(self._updater, self._reload_sources)
            self._update_thread = QThread(self)
            self._update_worker.moveToThread(self._update_thread)
            self._update_check_requested.connect(self._update_worker.check)
            self._update_download_requested.connect(self._update_worker.download)
            self._update_worker.check_done.connect(self._update_checked_relay)  # a signal of the window: queued into its thread
            self._update_checked_relay.connect(self._on_update_checked)
            self._update_worker.progress.connect(self._update_progress_relay)  # a signal of the window: queued into its thread
            self._update_progress_relay.connect(self._on_update_progress)
            self._update_worker.download_done.connect(self._update_downloaded_relay)  # a signal of the window: queued into its thread
            self._update_downloaded_relay.connect(self._on_update_downloaded)
            self._update_thread.start()
        return self._update_worker

    def _shutdown_updates(self) -> None:
        if self._update_worker is not None and self._update_thread is not None:
            self._update_worker.cancel()
            self._update_thread.quit()
            self._update_thread.wait(20000)

    # ------------------------------------------------------------ checking

    def start_update_check(self, force: bool = False) -> bool:
        """The background check: at most once a day, only when online, quiet when it fails. False: it did not start."""
        if self._updater is None or self._closed:
            return False
        if not force and not self._update_store.due(self._update_clock()):
            return False
        if not self._online():
            return False
        self._send_update_check(False, background=True)
        return True

    def _send_update_check(self, all_models: bool, background: bool) -> None:
        self._ensure_update_worker()
        self._update_check_requested.emit(self._update_model(), all_models, self._pedal_firmware, background)

    def _request_update_check(self, all_models: bool = False) -> None:
        if self._updater is None:
            return
        self.update_panel.set_scope(self._update_pedal_name())
        self.update_panel.set_checking()
        self._send_update_check(bool(all_models), background=False)

    @Slot(object, str, bool, bool)
    def _on_update_checked(self, result, error: str, background: bool, all_models: bool) -> None:
        if result is not None:
            self._update_store.mark_checked(self._update_clock())
            self._remote_firmware.update(result.firmware_versions)
            self._firmware_updates = set(result.firmware_updates)
            if not all_models:
                self._update_pending = len(result.pending)
                self._notice_dismissed = False
        if not background:
            if result is None:
                self.update_panel.set_error(S.UPDATE_ERROR_OFFLINE)
            else:
                self.update_panel.set_result(result, self._firmware_text(), self._updater.library_dir)
        self._refresh_update_notice()
        self.update_checked.emit()

    # ------------------------------------------------------------ notice

    def _firmware_newer(self) -> tuple[str, str | None] | None:
        """(published version, the pedal's version) when the connected pedal runs an older firmware."""
        model = self.connected_model
        remote = self._remote_firmware.get(model) if model is not None else None
        if remote is None or not self._pedal_firmware:
            return None
        greater = lib_updater.version_key(remote) > lib_updater.version_key(self._pedal_firmware) != ()
        if greater or model in self._firmware_updates:  # the channel's flag is what Guitar Lab itself goes by
            return remote, self._pedal_firmware
        return None

    def _firmware_text(self) -> str:
        newer = self._firmware_newer()
        if newer is None:
            return ""
        return S.firmware_notice(newer[0], self.models[self.connected_model].name
                                 if self.connected_model in self.models else "", newer[1])

    def _refresh_update_notice(self) -> None:
        pedal = self._update_pedal_name()
        firmware = self._firmware_text()
        if self._update_open or self._notice_dismissed or self._updater is None:
            text, button = "", False
        elif self._update_pending:
            text, button = S.update_notice(self._update_pending, pedal), True
        elif firmware:
            text, button = firmware, False
        else:
            text, button = "", False
        self.update_notice.set_full_text(text)
        self.update_notice.setVisible(bool(text))
        self.update_notice_button.setVisible(button)
        self.update_notice_dismiss.setVisible(bool(text))

    def _dismiss_update_notice(self) -> None:
        self._notice_dismissed = True
        self._refresh_update_notice()

    def _set_pedal_firmware(self, firmware: str | None) -> None:
        self._pedal_firmware = firmware or None
        self._refresh_update_notice()

    # ------------------------------------------------------------ the view

    def open_update_view(self) -> None:
        """The update view through its toggle, so every way in leaves the same state (the effects screen steps aside)."""
        if self._updater is None:
            return
        if self._effects_open:
            self.effects_toggle.setChecked(False)
        if self.update_toggle.isEnabled():
            self.update_toggle.setChecked(True)

    def _on_update_toggled(self, on: bool) -> None:
        self._update_open = on
        self.splitter.setEnabled(not on)
        self.splitter.setVisible(not on)
        self.update_panel.setVisible(on)
        self.edit_button.setEnabled(not on)
        self.library_button.setEnabled(not on)
        self._update_buttons()
        self._refresh_update_notice()
        if on:
            self.update_panel.set_idle()
            self._request_update_check(self.update_panel.all_models.isChecked())

    # ------------------------------------------------------------ downloading

    def _start_update_download(self, entries) -> None:
        if self._updater is None or not entries or self._update_busy:
            return
        self._update_busy = True
        self.update_panel.set_busy(True)
        self._update_buttons()
        self._ensure_update_worker()
        self._update_download_requested.emit(list(entries))

    def _cancel_update_download(self) -> None:
        if self._update_worker is not None:
            self._update_worker.cancel()

    @Slot(int, int, str)
    def _on_update_progress(self, done: int, total: int, name: str) -> None:
        self.update_panel.set_progress(done, total, name)

    @Slot(object, object, str)
    def _on_update_downloaded(self, report, loaded, error: str) -> None:
        self._update_busy = False
        if report is None:
            self.update_panel.set_busy(False)
            self.update_panel.set_error(S.UPDATE_ERROR_OFFLINE)
        else:
            if loaded is not None:
                self._apply_loaded_catalog(*loaded)
            self.update_panel.set_summary(report)
            self._update_pending = max(0, self._update_pending - report.ok_count)
            if report.ok_count:
                self.statusBar().showMessage(S.update_reloaded(report.ok_count))
        self._update_buttons()
        self._refresh_update_notice()
        self.update_downloaded.emit()

