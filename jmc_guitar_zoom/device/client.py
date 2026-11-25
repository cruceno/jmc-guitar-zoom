"""Pedal client: request/response matching, timeouts and typed errors.

The client is synchronous and thread-safe (one request at a time). It is meant
to run on a worker thread; callbacks registered with :meth:`PedalClient.subscribe`
are invoked on whichever thread is currently reading from the transport.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from . import sysex
from .errors import PedalError, PedalFileNotFound, PedalProtocolError, PedalTimeout
from .messages import ControlChange, Message, ProgramChange, SysexMessage, TunerReading
from .sysex import DiskUsage, Identity, PatchInfo
from .transport import Transport

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 3.0
MAX_FILE_BLOCKS = 4096


class _ModeGuard:
    """Returned by editor_mode()/pc_mode(); leaving a ``with`` turns the mode off."""

    def __init__(self, turn_off: Callable[[], None] | None) -> None:
        self._turn_off = turn_off

    def __enter__(self) -> "_ModeGuard":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._turn_off is not None:
            try:
                self._turn_off()
            except PedalError:
                if exc_type is None:
                    raise
        return False


class PedalClient:
    def __init__(self, transport: Transport, *, model_id: int = sysex.DEFAULT_MODEL,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.transport = transport
        self.model_id = model_id
        self.timeout = timeout
        self._lock = threading.RLock()
        self._subscribers: list[Callable[[Any], None]] = []
        self._info: PatchInfo | None = None
        self._tuner_note: str | None = None
        self._tuner_offset = 0

    # ------------------------------------------------------------ events

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Receive unsolicited traffic: TunerReading events and raw transport messages."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def _dispatch(self, msg: Message) -> None:
        event: Any = msg
        if isinstance(msg, ControlChange):
            if msg.control == sysex.CC_TUNER_NOTE:
                notes = sysex.TUNER_NOTES
                self._tuner_note = notes[msg.value] if msg.value < len(notes) else None
                event = TunerReading(self._tuner_note, self._tuner_offset)
            elif msg.control == sysex.CC_TUNER_CENTS:
                self._tuner_offset = msg.value - 8
                event = TunerReading(self._tuner_note, self._tuner_offset)
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:  # a faulty listener must never break pedal requests
                log.exception("Pedal event subscriber %r failed", callback)

    def poll(self, timeout: float = 0) -> int:
        """Dispatch pending unsolicited messages; returns how many were handled."""
        with self._lock:
            count = 0
            wait = timeout
            while (msg := self.transport.receive(wait)) is not None:
                self._dispatch(msg)
                count += 1
                wait = 0
            return count

    # ------------------------------------------------------------ plumbing

    def _reply_is(self, *prefix: int) -> Callable[[bytes], bool]:
        want = sysex.header(self.model_id) + bytes(prefix)
        return lambda data: data.startswith(want)

    def _is_ack(self, data: bytes) -> bool:
        """Acknowledgement of PC mode (52/53), editor mode (50/51) and patch write (45).

        All are answered with exactly ``52 00 <model> 00 00`` on a real A1 FOUR (fw 1.01);
        any other reply is not an ack.
        """
        return data == sysex.header(self.model_id) + b"\x00\x00"

    def _request(self, payload: bytes, accept: Callable[[bytes], bool],
                 timeout: float | None = None) -> bytes:
        limit = self.timeout if timeout is None else timeout
        with self._lock:
            self.poll(0)  # late replies of earlier requests must not match this one
            self.transport.send(SysexMessage(payload))
            deadline = time.monotonic() + limit
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PedalTimeout(f"no reply to {payload[:6].hex()} within {limit:g}s")
                msg = self.transport.receive(remaining)
                if msg is None:
                    continue
                if isinstance(msg, SysexMessage) and accept(msg.data):
                    return msg.data
                self._dispatch(msg)

    def _send(self, msg: Message) -> None:
        with self._lock:
            self.transport.send(msg)

    def _bank_size(self) -> int:
        return (self._info or self.patch_info()).patches_per_bank

    # ------------------------------------------------------------ device

    def identify(self, timeout: float | None = None) -> Identity:
        data = self._request(
            sysex.identity_request(),
            lambda d: len(d) >= 4 and d[0] == 0x7E and d[2:4] == b"\x06\x02",
            timeout,
        )
        ident = sysex.parse_identity_reply(data)
        self.model_id = ident.model
        return ident

    def patch_info(self, timeout: float | None = None) -> PatchInfo:
        data = self._request(sysex.patch_info_request(self.model_id), self._reply_is(*sysex.REPLY_PATCH_INFO), timeout)
        info = sysex.parse_patch_info(data, self.model_id)
        if info.patches_per_bank < 1:
            raise PedalProtocolError("pedal reported zero patches per bank")
        self._info = info
        return info

    def read_patch(self, location: int, timeout: float | None = None) -> bytes:
        """Read a stored patch; ``location`` is 1-based."""
        request = sysex.read_patch_request(location, self._bank_size(), self.model_id)
        return sysex.parse_patch_reply(self._request(request, self._reply_is(*sysex.REPLY_READ_PATCH), timeout), self.model_id)

    def write_patch(self, location: int, data: bytes, timeout: float | None = None) -> None:
        request = sysex.write_patch_request(location, data, self._bank_size(), self.model_id)
        self._request(request, self._is_ack, timeout)

    def read_current_patch(self, timeout: float | None = None) -> bytes:
        data = self._request(sysex.read_current_patch_request(self.model_id),
                             self._reply_is(*sysex.REPLY_CURRENT_PATCH), timeout)
        return sysex.parse_current_patch_reply(data, self.model_id)

    def set_param(self, slot: int, param: int, value: int) -> None:
        """Live-edit a parameter of the current patch. The pedal does not acknowledge it."""
        self._send(SysexMessage(sysex.set_param(slot, param, value, self.model_id)))

    def set_patch_name_char(self, position: int, char: str) -> None:
        self._send(SysexMessage(sysex.set_patch_name_char(position, char, self.model_id)))

    def set_patch_volume(self, value: int) -> None:
        self._send(SysexMessage(sysex.set_patch_volume(value, self.model_id)))

    def select_patch(self, location: int) -> None:
        """Select a stored patch (1-based location) with CC0/CC32 + Program Change."""
        bank, program = sysex.location_to_bank(location, self._bank_size())
        with self._lock:
            self.transport.send(ControlChange(0, (bank >> 7) & 0x7F))
            self.transport.send(ControlChange(32, bank & 0x7F))
            self.transport.send(ProgramChange(program))

    # ------------------------------------------------------------ modes

    def editor_mode(self, on: bool = True, timeout: float | None = None) -> _ModeGuard:
        """Switch editor mode; usable as a context manager that switches it off again."""
        self._request(sysex.editor_mode(on, self.model_id), self._is_ack, timeout)
        return _ModeGuard(lambda: self.editor_mode(False, timeout)) if on else _ModeGuard(None)

    def pc_mode(self, on: bool = True, timeout: float | None = None) -> _ModeGuard:
        """Switch PC mode; ``with client.pc_mode(True):`` always turns it off on exit."""
        self._request(sysex.pc_mode(on, self.model_id), self._is_ack, timeout)
        return _ModeGuard(lambda: self.pc_mode(False, timeout)) if on else _ModeGuard(None)

    def tuner(self, on: bool) -> None:
        """Start/stop the tuner. Readings arrive as TunerReading events (see poll)."""
        self._send(SysexMessage(sysex.tuner(on, self.model_id)))

    # ------------------------------------------------------------ files

    def _file_step(self, payload: bytes, timeout: float | None = None) -> bytes:
        """Every ``60`` command is answered by exactly one ``60`` reply."""
        return self._request(payload, self._reply_is(0x60), timeout)

    def _file_close(self, timeout: float | None = None) -> None:
        for payload in sysex.file_close_request(self.model_id):
            self._file_step(payload, timeout)

    def list_files(self, timeout: float | None = None) -> list[str]:
        with self._lock:
            names: list[str] = []
            first = True
            while True:
                reply = self._file_step(sysex.file_list_request(first, self.model_id), timeout)
                first = False
                name = sysex.parse_file_name_reply(reply, self.model_id)
                if not name:
                    break
                names.append(name)
            self._file_close(timeout)
            return names

    def read_file(self, name: str, timeout: float | None = None) -> bytes:
        """Download a file. Mirrors zoomzt2's file_check + file_download + file_close."""
        with self._lock:
            self._file_step(sysex.file_check_request(name, self.model_id), timeout)
            status = self._file_step(sysex.file_status_request(self.model_id), timeout)
            self._file_step(sysex.file_check_done_request(self.model_id), timeout)
            if not sysex.parse_file_check_reply(status):
                raise PedalFileNotFound(name)
            try:
                return self._download(name, timeout)
            finally:
                try:
                    self._file_close(timeout)
                except PedalError:
                    pass  # never mask the download error with a close failure

    def _download(self, name: str, timeout: float | None) -> bytes:
        # zoomzt2 sends the open command twice (it re-sends the packet it just
        # extended in place); that known-good sequence is kept.
        open_req = sysex.file_open_read_request(name, self.model_id)
        self._file_step(open_req, timeout)
        self._file_step(open_req, timeout)
        data = bytearray()
        for _ in range(MAX_FILE_BLOCKS):
            self._file_step(sysex.file_status_request(self.model_id), timeout)
            self._file_step(sysex.file_read_block_request(self.model_id), timeout)
            reply = self._file_step(sysex.file_status_request(self.model_id), timeout)
            block = sysex.parse_file_block_reply(reply, self.model_id)
            if block is None:
                return bytes(data)
            data += block
        raise PedalProtocolError(f"file {name!r} exceeds {MAX_FILE_BLOCKS} blocks")

    def write_file(self, name: str, data: bytes, timeout: float | None = None) -> None:
        """Upload a file, replacing any file of that name.

        Mirrors zoomzt2's file_upload + file_close: delete, open for write, a status
        request, then 512-byte blocks each followed by a status request, then close.
        The status replies carry no known success code, so callers verify the upload
        by reading the file back.
        """
        sysex.check_file_name(name)
        if not data:
            raise ValueError("refusing to upload an empty file")
        with self._lock:
            self._file_step(sysex.file_delete_request(name, self.model_id), timeout)
            self._file_step(sysex.file_open_write_request(name, self.model_id), timeout)
            self._file_step(sysex.file_status_request(self.model_id), timeout)
            for start in range(0, len(data), sysex.FILE_BLOCK_SIZE):
                block = data[start:start + sysex.FILE_BLOCK_SIZE]
                self._file_step(sysex.file_write_block_request(block, self.model_id), timeout)
                self._file_step(sysex.file_status_request(self.model_id), timeout)
            self._file_close(timeout)

    def delete_file(self, name: str, timeout: float | None = None) -> None:
        """Delete a file (zoomzt2's file_delete + file_close)."""
        sysex.check_file_name(name)
        with self._lock:
            self._file_step(sysex.file_delete_request(name, self.model_id), timeout)
            self._file_close(timeout)

    def disk_usage(self, timeout: float | None = None) -> DiskUsage:
        data = self._file_step(sysex.disk_usage_request(self.model_id), timeout)
        return sysex.parse_disk_usage(data, self.model_id)
