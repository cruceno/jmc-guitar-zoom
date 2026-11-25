"""Worker object that owns the :class:`PedalClient` and does all pedal I/O.

Create it on the GUI thread, call ``moveToThread`` with a started ``QThread``
and trigger its slots through :meth:`PedalWorker.request` (queued) or through
signals connected to them. Every failure becomes an ``error`` signal.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QTimer, Qt, Signal, Slot

from zoomstudio.device import PedalClient, PedalError, TunerReading
from zoomstudio.effects import installer
from zoomstudio.effects.flst import FLST_NAME
from zoomstudio.device.transport import Transport
from zoomstudio.patches import library
from zoomstudio.patches.backup import write_backup
from zoomstudio.patches.edit import compare_patches
from zoomstudio.patches.model import Patch
from zoomstudio.patches.zptc import parse_zptc

from . import strings as S

TransportFactory = Callable[[], Transport]


def describe_error(exc: BaseException) -> str:
    """Spanish sentence for a pedal error, with the technical detail of low-level errors appended."""
    from zoomstudio.device.errors import ChecksumError, PedalProtocolError, PedalTimeout

    if isinstance(exc, PedalTimeout):
        return S.with_detail(S.ERR_NO_REPLY, exc)
    if isinstance(exc, (ChecksumError, PedalProtocolError)):
        return S.with_detail(S.ERR_BAD_REPLY, exc)
    return str(exc) or type(exc).__name__


TUNER_POLL_MS = 50  # how often the worker thread drains tuner traffic while the tuner is on


class _ReadBackError(Exception):
    """The pedal's read-back is invalid or differs from what was sent."""


class PedalWorker(QObject):
    connected = Signal(object, object)  # Identity, PatchInfo
    disconnected = Signal()
    patch_loaded = Signal(int, object)  # 1-based location, Patch
    disk_usage = Signal(object)  # DiskUsage
    progress = Signal(int, int)  # done, total
    loading_finished = Signal()
    patch_saved = Signal(int, object, str)  # location, patch read back from the pedal, backup path
    save_finished = Signal(int, bool)  # location, success (always emitted last)
    backup_progress = Signal(str, int, int)  # phase ("patches" / "files"), done, total
    backup_finished = Signal(str, bool)  # patches folder ("" if none was created), success (emitted last)
    queue_finished = Signal(object, int)  # locations written and verified, failed location (0: none)
    tuner_reading = Signal(object, int)  # note name or None, offset -7..+7 (0: in tune)
    tuner_state = Signal(bool)  # the worker turned the tuner off by itself (refused, I/O error, disconnect)
    effects_state = Signal(object, object, object)  # FLST_SEQ.ZT2 bytes, file names on the pedal, DiskUsage
    effects_state_failed = Signal()  # the state could not be read (the reason went through ``error``)
    effect_changed = Signal(str, bool)  # pedal file name, installed (emitted when the change was verified)
    effect_change_finished = Signal(bool)  # success (always emitted last)
    error = Signal(str)

    def __init__(self, transport_factory: TransportFactory, timeout: float = 3.0) -> None:
        super().__init__()
        self._factory = transport_factory
        self._timeout = timeout
        self._client: PedalClient | None = None
        self._transport: Transport | None = None
        self._count = 0
        self._identity = None
        self._info = None
        self._cancel = threading.Event()
        self._tuner_timer: QTimer | None = None
        self._tuner_unsubscribe: Callable[[], None] | None = None

    # ------------------------------------------------------------ helpers

    def request(self, slot_name: str) -> None:
        """Run one of this worker's slots on its own thread (queued call)."""
        QMetaObject.invokeMethod(self, slot_name, Qt.ConnectionType.QueuedConnection)

    def cancel(self) -> None:
        """Ask a running ``load_all_patches`` to stop; safe to call from any thread."""
        self._cancel.set()

    def _fail(self, exc: BaseException) -> None:
        self.error.emit(describe_error(exc))

    def _require_client(self) -> PedalClient | None:
        if self._client is None:
            self.error.emit(S.ERR_NOT_CONNECTED)
        return self._client

    def _close_transport(self) -> None:
        self._stop_tuner_polling()
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
        self._identity, self._info = identity, info
        self._count = info.count
        self.connected.emit(identity, info)

    @Slot()
    def disconnect_pedal(self) -> None:
        self._tuner_off_quietly()
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
                        self.error.emit(S.err_patch(location + 9, describe_error(exc)))
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

    @Slot()
    def load_effects_state(self) -> None:
        """Read the effect list, the file names and the disk usage in one PC-mode session."""
        client = self._require_client()
        if client is None:
            self.effects_state_failed.emit()
            return
        try:
            with client.pc_mode(True):
                flst_bytes = client.read_file(FLST_NAME)
                files = client.list_files()
                usage = client.disk_usage()
        except (PedalError, OSError) as exc:
            self._fail(exc)
            self.effects_state_failed.emit()
            return
        self.effects_state.emit(flst_bytes, files, usage)

    @Slot(str, object, object)
    def install_effect_file(self, name: str, path, backup_dir) -> None:
        """Upload the local ``.zd2`` as ``name`` and flag it installed (the installer verifies both by read-back)."""
        client = self._require_client()
        if client is None or not self._backup_dir_ok(backup_dir):
            self.effect_change_finished.emit(False)
            return
        try:
            data = Path(path).read_bytes()
            installer.install_effect(client, data, name, Path(backup_dir))
        except (PedalError, OSError, installer.EffectInstallError) as exc:
            self.error.emit(S.err_effect_change(name, True, describe_error(exc)))
            self.effect_change_finished.emit(False)
            return
        self.effect_changed.emit(name, True)
        self.effect_change_finished.emit(True)

    @Slot(str, object, object)
    def repair_effect_file(self, name: str, path, backup_dir) -> None:
        """Upload only the missing file of an effect the list already marks installed (the list is not changed)."""
        client = self._require_client()
        if client is None or not self._backup_dir_ok(backup_dir):
            self.effect_change_finished.emit(False)
            return
        try:
            data = Path(path).read_bytes()
            installer.repair_effect(client, data, name, Path(backup_dir))
        except (PedalError, OSError, installer.EffectInstallError) as exc:
            self.error.emit(S.err_effect_repair(name, describe_error(exc)))
            self.effect_change_finished.emit(False)
            return
        self.effect_changed.emit(name, True)
        self.effect_change_finished.emit(True)

    @Slot(str, object, object)
    def remove_effect_file(self, name: str, backup_dir, in_use) -> None:
        """Clear the flag of ``name`` and delete its file; the installer refuses effects that ``in_use`` lists."""
        client = self._require_client()
        if client is None or not self._backup_dir_ok(backup_dir):
            self.effect_change_finished.emit(False)
            return
        try:
            installer.remove_effect(client, name, Path(backup_dir), in_use)
        except (PedalError, OSError, installer.EffectInstallError) as exc:
            self.error.emit(S.err_effect_change(name, False, describe_error(exc)))
            self.effect_change_finished.emit(False)
            return
        self.effect_changed.emit(name, False)
        self.effect_change_finished.emit(True)

    def _backup_dir_ok(self, backup_dir) -> bool:
        if backup_dir is None:
            self.error.emit(S.ERR_NO_BACKUP_DIR)
        return backup_dir is not None

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
            self.error.emit(S.ERR_NO_BACKUP_DIR)
            self.save_finished.emit(location, False)
            return
        readback: bytes | None = None
        backup = None
        guard_error: BaseException | None = None
        try:
            with client.pc_mode(True):
                try:
                    readback, backup = self._read_write_read(client, location, data, backup_dir)
                except (PedalError, OSError) as exc:
                    guard_error = exc
        except (PedalError, OSError) as exc:  # PC mode on/off failed
            if guard_error is None:
                guard_error = exc
        if readback is None:
            self._fail(guard_error or RuntimeError(S.ERR_SAVE_FAILED))
            self.save_finished.emit(location, False)
            return
        if guard_error is not None:
            self.error.emit(S.err_pc_mode_off(guard_error))
        try:
            stored = self._verify(location, data, readback)
        except _ReadBackError as exc:
            self.error.emit(str(exc))
            self.save_finished.emit(location, False)
            return
        self.patch_saved.emit(location, stored, str(backup))
        self.save_finished.emit(location, True)

    @staticmethod
    def _read_write_read(client: PedalClient, location: int, data: bytes, backup_dir) -> tuple[bytes, Path]:
        """Inside PC mode: read the slot, back it up, write ``data``, read the slot back.

        Nothing is written unless the backup of the previous content was stored.
        """
        previous = client.read_patch(location)
        backup = write_backup(backup_dir, location, previous)
        client.write_patch(location, data)
        return client.read_patch(location), backup

    @staticmethod
    def _verify(location: int, data: bytes, readback: bytes) -> Patch:
        try:
            stored = parse_zptc(readback)
            diffs = compare_patches(parse_zptc(data), stored)
        except ValueError as exc:
            raise _ReadBackError(S.err_readback_invalid(location + 9, exc)) from exc
        if diffs:
            raise _ReadBackError(S.err_readback_differs(location + 9, diffs))
        return stored

    @Slot(object, object)
    def write_patches(self, items, backup_dir) -> None:
        """Safe write of several slots (``items`` = ``[(location, data), ...]``) under one PC mode.

        Each slot goes through the same steps as :meth:`save_patch` (backup of the previous content,
        write, read-back compare). The queue stops at the first failure: later slots are not touched.
        ``queue_finished`` reports the verified locations and the failed one.
        """
        client = self._require_client()
        if client is None:
            self.queue_finished.emit([], items[0][0] if items else 0)
            return
        if backup_dir is None:
            self.error.emit(S.ERR_NO_BACKUP_DIR)
            self.queue_finished.emit([], items[0][0] if items else 0)
            return
        self._cancel.clear()
        written: list[int] = []
        failed = 0
        try:
            with client.pc_mode(True):
                for location, data in items:
                    if self._cancel.is_set():
                        failed = location
                        self.error.emit(self._stopped(location, written, S.CANCELLED))
                        break
                    try:
                        readback, backup = self._read_write_read(client, location, data, backup_dir)
                        stored = self._verify(location, data, readback)
                    except (PedalError, OSError, _ReadBackError) as exc:
                        failed = location
                        self.error.emit(self._stopped(location, written, describe_error(exc)))
                        break
                    written.append(location)
                    self.patch_saved.emit(location, stored, str(backup))
        except (PedalError, OSError) as exc:  # PC mode on/off failed
            self.error.emit(S.err_pc_mode_switch(exc))
            if not written and not failed and items:
                failed = items[0][0]
        self.queue_finished.emit(written, failed)

    @staticmethod
    def _stopped(location: int, written: list[int], why: str) -> str:
        done = ", ".join(str(n + 9) for n in written) or S.NONE_WRITTEN
        return S.err_queue_stopped(location + 9, why, done)

    @Slot(object, bool, object)
    def backup_all(self, dest_parent, with_files: bool, stamp=None) -> None:
        """Save every patch as ``NNN.zptc`` plus ``manifest.json`` (and optionally every pedal file).

        Read-only on the pedal. Folders are created exclusively (an existing one is refused before
        anything is asked of the pedal); ``backup_finished`` is emitted last.
        """
        client = self._require_client()
        if client is None or self._info is None:
            self.backup_finished.emit("", False)
            return
        stamp = library.timestamp(stamp or None)
        try:
            dest = library.new_folder(dest_parent, "backup", stamp)
        except FileExistsError:
            self.error.emit(S.err_backup_folder_exists(stamp))
            self.backup_finished.emit("", False)
            return
        except OSError as exc:
            self._fail(exc)
            self.backup_finished.emit("", False)
            return
        self._cancel.clear()
        info, identity = self._info, self._identity
        manifest = {
            "created": stamp, "model_id": f"0x{identity.model:02X}", "patch_count": info.count,
            "patch_size": info.patch_size, "patches_per_bank": info.patches_per_bank, "patches": [],
        }
        ok = True
        try:
            with client.pc_mode(True):
                ok = self._backup_patches(client, dest, manifest)
                if ok and with_files:
                    ok = self._backup_files(client, Path(dest_parent), stamp, manifest)
        except (PedalError, OSError) as exc:
            self._fail(exc)
            ok = False
        if self._cancel.is_set():
            manifest["cancelled"] = True
            ok = False
        try:
            library.write_manifest(dest, manifest)
        except OSError as exc:
            self._fail(exc)
            ok = False
        self.backup_finished.emit(str(dest), ok)

    def _backup_patches(self, client: PedalClient, dest: Path, manifest: dict) -> bool:
        ok, streak = True, 0
        for location in range(1, self._count + 1):
            if self._cancel.is_set():
                return False
            entry: dict = {"location": location}
            try:
                data = client.read_patch(location)
                name = f"{location:03d}.zptc"
                library.write_new(dest / name, data)
                entry.update(file=name, bytes=len(data), status="ok")
                streak = 0
            except PedalError as exc:
                entry["status"] = f"error: {exc}"
                ok, streak = False, streak + 1
                self.error.emit(S.err_patch(location + 9, describe_error(exc)))
            manifest["patches"].append(entry)
            self.backup_progress.emit("patches", location, self._count)
            if streak >= 3:
                self.error.emit(S.ERR_BACKUP_ABORTED)
                return False
        return ok

    def _backup_files(self, client: PedalClient, parent: Path, stamp: str, manifest: dict) -> bool:
        names = client.list_files()
        try:
            dest = library.new_folder(parent, "pedal-files", stamp)
        except FileExistsError:
            self.error.emit(S.err_files_folder_exists(stamp))
            return False
        ok = True
        files = []
        for i, name in enumerate(names, start=1):
            if self._cancel.is_set():
                return False
            try:
                data = client.read_file(name)
                library.write_new(dest / library.safe_file_name(name), data)
                files.append({"name": name, "bytes": len(data)})
            except PedalError as exc:
                ok = False
                files.append({"name": name, "error": str(exc)})
                self.error.emit(S.err_file(name, describe_error(exc)))
            self.backup_progress.emit("files", i, len(names))
        manifest["pedal_files_folder"] = dest.name
        manifest["pedal_files"] = files
        return ok

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

    # -------------------------------------------------------------- tuner

    @property
    def tuner_active(self) -> bool:
        return self._tuner_timer is not None

    @Slot(bool)
    def set_tuner(self, on: bool) -> None:
        self.tuner_on() if on else self.tuner_off()

    @Slot()
    def tuner_on(self) -> None:
        """Switch the pedal tuner on and poll its CC 98/99 traffic on this thread."""
        client = self._require_client()
        if client is None:
            self.tuner_state.emit(False)
            return
        if self.tuner_active:
            return
        try:
            # The pedal only streams tuner CC 98/99 in editor mode (observed on a real A1 FOUR).
            client.editor_mode(True)
            client.tuner(True)
        except (PedalError, OSError) as exc:
            self._fail(exc)
            self._leave_editor_mode_quietly(client)
            self.tuner_state.emit(False)
            return
        self._tuner_unsubscribe = client.subscribe(self._on_tuner_event)
        self._tuner_timer = QTimer(self)  # lives on the worker's thread (tuner_on runs there)
        self._tuner_timer.setInterval(TUNER_POLL_MS)
        self._tuner_timer.timeout.connect(self._poll_tuner)
        self._tuner_timer.start()

    @Slot()
    def tuner_off(self) -> None:
        was_active = self.tuner_active
        self._stop_tuner_polling()
        client = self._client
        if client is not None and was_active:
            try:
                client.tuner(False)
            except (PedalError, OSError) as exc:
                self._fail(exc)
            finally:  # the tuner only runs in editor mode: always leave it, even if tuner off failed
                try:
                    client.editor_mode(False)
                except (PedalError, OSError) as exc:
                    self._fail(exc)

    def _tuner_off_quietly(self) -> None:
        """Before closing the port: send tuner off if it is on; never raise."""
        if not self.tuner_active:
            return
        client = self._client
        self._stop_tuner_polling()
        if client is not None:
            try:
                client.tuner(False)
            except Exception:
                pass
            self._leave_editor_mode_quietly(client)
        self.tuner_state.emit(False)

    @staticmethod
    def _leave_editor_mode_quietly(client) -> None:
        try:
            client.editor_mode(False)
        except Exception:
            pass

    def _stop_tuner_polling(self) -> None:
        timer, self._tuner_timer = self._tuner_timer, None
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        unsubscribe, self._tuner_unsubscribe = self._tuner_unsubscribe, None
        if unsubscribe is not None:
            unsubscribe()

    def _on_tuner_event(self, event) -> None:
        if isinstance(event, TunerReading):
            self.tuner_reading.emit(event.note, event.offset)

    def _poll_tuner(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            client.poll(0)  # non-blocking; drains whatever the pedal sent since the last tick
        except (PedalError, OSError) as exc:
            self._stop_tuner_polling()
            self._fail(exc)
            self._leave_editor_mode_quietly(client)
            self.tuner_state.emit(False)
