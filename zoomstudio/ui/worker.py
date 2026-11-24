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
from zoomstudio.patches.backup import write_backup
from zoomstudio.patches.edit import compare_patches
from zoomstudio.patches.zptc import parse_zptc

TransportFactory = Callable[[], Transport]


class PedalWorker(QObject):
    connected = Signal(object, object)  # Identity, PatchInfo
    disconnected = Signal()
    patch_loaded = Signal(int, object)  # 1-based location, Patch
    disk_usage = Signal(object)  # DiskUsage
    progress = Signal(int, int)  # done, total
    loading_finished = Signal()
    patch_saved = Signal(int, object, str)  # location, patch read back from the pedal, backup path
    save_finished = Signal(int, bool)  # location, success (always emitted last)
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

    @Slot(int, object, object)
    def save_patch(self, location: int, data: bytes, backup_dir) -> None:
        """Safe write of one patch: back up the slot, write, read back and compare.

        Order on the wire: PC mode on, read ``46``, write ``45``, read ``46``, PC mode off.
        The slot's previous content is stored under ``backup_dir`` before anything is written;
        if that fails nothing is written. ``patch_saved`` is emitted only when the read-back
        matches what was sent.
        """
        client = self._require_client()
        if client is None:
            self.save_finished.emit(location, False)
            return
        if backup_dir is None:
            self.error.emit("No backup folder configured: refusing to write to the pedal")
            self.save_finished.emit(location, False)
            return
        readback: bytes | None = None
        backup = None
        guard_error: BaseException | None = None
        try:
            with client.pc_mode(True):
                try:
                    previous = client.read_patch(location)
                    backup = write_backup(backup_dir, location, previous)
                    client.write_patch(location, data)
                    readback = client.read_patch(location)
                except (PedalError, OSError) as exc:
                    guard_error = exc
        except (PedalError, OSError) as exc:  # PC mode on/off failed
            if guard_error is None:
                guard_error = exc
        if readback is None:
            self._fail(guard_error or RuntimeError("save failed"))
            self.save_finished.emit(location, False)
            return
        if guard_error is not None:
            self.error.emit(f"PC mode could not be switched off cleanly: {guard_error}")
        try:
            stored = parse_zptc(readback)
            diffs = compare_patches(parse_zptc(data), stored)
        except ValueError as exc:
            self.error.emit(f"Read-back of patch {location + 9} is not valid: {exc}")
            self.save_finished.emit(location, False)
            return
        if diffs:
            self.error.emit(f"Patch {location + 9} read-back differs from what was sent: "
                            + "; ".join(diffs[:4]))
            self.save_finished.emit(location, False)
            return
        self.patch_saved.emit(location, stored, str(backup))
        self.save_finished.emit(location, True)

    @Slot(int, int, int)
    def send_param(self, slot: int, param: int, value: int) -> None:
        """Live edit: send one ``64 03`` parameter change (fire and forget)."""
        client = self._client
        if client is None:
            return
        try:
            client.set_param(slot, param, value)
        except (PedalError, OSError, ValueError) as exc:
            self._fail(exc)

    @Slot(int)
    def select_patch(self, location: int) -> None:
        client = self._client
        if client is None:
            return
        try:
            client.select_patch(location)
        except (PedalError, OSError, ValueError) as exc:
            self._fail(exc)
