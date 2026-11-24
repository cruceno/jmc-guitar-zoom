"""Worker object that owns the :class:`PedalClient` and does all pedal I/O.

Create it on the GUI thread, call ``moveToThread`` with a started ``QThread``
and trigger its slots through :meth:`PedalWorker.request` (queued) or through
signals connected to them. Every failure becomes an ``error`` signal.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot

from zoomstudio.device import PedalClient, PedalError
from zoomstudio.device.transport import Transport
from zoomstudio.patches.zptc import parse_zptc

TransportFactory = Callable[[], Transport]


class PedalWorker(QObject):
    connected = Signal(object, object)  # Identity, PatchInfo
    disconnected = Signal()
    patch_loaded = Signal(int, object)  # 1-based location, Patch
    disk_usage = Signal(object)  # DiskUsage
    progress = Signal(int, int)  # done, total
    loading_finished = Signal()
    error = Signal(str)

    def __init__(self, transport_factory: TransportFactory, timeout: float = 3.0) -> None:
        super().__init__()
        self._factory = transport_factory
        self._timeout = timeout
        self._client: PedalClient | None = None
        self._transport: Transport | None = None
        self._count = 0
        self._cancel = threading.Event()

    # ------------------------------------------------------------ helpers

    def request(self, slot_name: str) -> None:
        """Run one of this worker's slots on its own thread (queued call)."""
        QMetaObject.invokeMethod(self, slot_name, Qt.ConnectionType.QueuedConnection)

    def cancel(self) -> None:
        """Ask a running ``load_all_patches`` to stop; safe to call from any thread."""
        self._cancel.set()

    def _fail(self, exc: BaseException) -> None:
        self.error.emit(str(exc) or type(exc).__name__)

    def _require_client(self) -> PedalClient | None:
        if self._client is None:
            self.error.emit("Not connected to the pedal")
        return self._client

    def _close_transport(self) -> None:
        transport, self._transport, self._client = self._transport, None, None
        if transport is not None:
            try:
                transport.close()
            except Exception:  # closing must never raise into the event loop
                pass

    # -------------------------------------------------------------- slots

    @Slot()
    def connect_pedal(self) -> None:
        self._close_transport()
        try:
            self._transport = self._factory()
            client = PedalClient(self._transport, timeout=self._timeout)
            identity = client.identify()
            info = client.patch_info()
        except (PedalError, OSError, ConnectionError, ValueError) as exc:
            self._close_transport()
            self._fail(exc)
            return
        self._client = client
        self._count = info.count
        self.connected.emit(identity, info)

    @Slot()
    def disconnect_pedal(self) -> None:
        self._close_transport()
        self.disconnected.emit()

    @Slot()
    def load_all_patches(self) -> None:
        client = self._require_client()
        if client is None:
            return
        self._cancel.clear()
        try:
            with client.pc_mode(True):
                for location in range(1, self._count + 1):
                    if self._cancel.is_set():
                        break
                    try:
                        patch = parse_zptc(client.read_patch(location))
                    except ValueError as exc:  # one undecodable patch must not stop the rest
                        self.error.emit(f"Patch {location + 9}: {exc}")
                        continue
                    self.patch_loaded.emit(location, patch)
                    self.progress.emit(location, self._count)
        except (PedalError, OSError) as exc:
            self._fail(exc)
        self.loading_finished.emit()

    @Slot()
    def refresh_disk_usage(self) -> None:
        client = self._require_client()
        if client is None:
            return
        try:
            with client.pc_mode(True):
                usage = client.disk_usage()
        except (PedalError, OSError) as exc:
            self._fail(exc)
            return
        self.disk_usage.emit(usage)
