"""MIDI transports: a small protocol, a mido/rtmidi implementation and a fake."""

from __future__ import annotations

import queue
from typing import Protocol

from .messages import ControlChange, Message, ProgramChange, SysexMessage

DEFAULT_PORT_PREFIX = "ZOOM G"


class Transport(Protocol):
    def send(self, msg: Message) -> None: ...

    def receive(self, timeout: float | None = None) -> Message | None:
        """Next incoming message, or None after ``timeout`` seconds (0 = do not wait)."""
        ...

    def close(self) -> None: ...


def find_port_name(names: list[str], prefix: str = DEFAULT_PORT_PREFIX, skip: int = 0) -> str | None:
    matches = [n for n in names if n.startswith(prefix)]
    return matches[skip] if skip < len(matches) else None


class _QueueReceiver:
    def __init__(self) -> None:
        self._queue: queue.Queue[Message] = queue.Queue()

    def _put(self, msg: Message) -> None:
        self._queue.put(msg)

    def receive(self, timeout: float | None = None) -> Message | None:
        try:
            if timeout is not None and timeout <= 0:
                return self._queue.get_nowait()
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


class MidoTransport(_QueueReceiver):
    """Real MIDI I/O through mido + python-rtmidi.

    The input port uses a callback (rtmidi thread) that feeds a thread-safe queue.
    """

    def __init__(self, input_name: str, output_name: str) -> None:
        import mido

        super().__init__()
        self.input_name = input_name
        self.output_name = output_name
        self._in = None
        self._out = None
        try:
            self._out = mido.open_output(output_name)
            self._in = mido.open_input(input_name, callback=self._on_mido)
        except Exception:
            self.close()
            raise

    @classmethod
    def open(cls, prefix: str = DEFAULT_PORT_PREFIX, skip: int = 0) -> "MidoTransport":
        import mido

        in_name = find_port_name(mido.get_input_names(), prefix, skip)
        out_name = find_port_name(mido.get_output_names(), prefix, skip)
        if in_name is None or out_name is None:
            raise ConnectionError(f"no MIDI port found with prefix {prefix!r}")
        return cls(in_name, out_name)

    @staticmethod
    def to_mido(msg: Message):
        import mido

        if isinstance(msg, SysexMessage):
            return mido.Message("sysex", data=list(msg.data))
        if isinstance(msg, ControlChange):
            return mido.Message("control_change", channel=msg.channel, control=msg.control, value=msg.value)
        return mido.Message("program_change", channel=msg.channel, program=msg.program)

    @staticmethod
    def from_mido(m) -> Message | None:
        if m.type == "sysex":
            return SysexMessage(bytes(m.data))
        if m.type == "control_change":
            return ControlChange(control=m.control, value=m.value, channel=m.channel)
        if m.type == "program_change":
            return ProgramChange(program=m.program, channel=m.channel)
        return None

    def _on_mido(self, m) -> None:
        msg = self.from_mido(m)
        if msg is not None:
            self._put(msg)

    def send(self, msg: Message) -> None:
        if self._out is None:
            raise ConnectionError("transport is closed")
        self._out.send(self.to_mido(msg))

    def close(self) -> None:
        inp, out = self._in, self._out
        self._in = self._out = None
        if inp is not None:
            inp.callback = None
            inp.close()
        if out is not None:
            out.close()


class FakeTransport(_QueueReceiver):
    """Scripted transport for tests. Never touches MIDI hardware.

    ``on(prefix, *replies)`` registers one response set for sysex requests that
    start with ``prefix``: the next matching send delivers all of ``replies``.
    Several calls with the same prefix queue several sets, used one per send.
    A send with no remaining set gets no reply (the client then times out).
    """

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[Message] = []
        self.closed = False
        self._rules: list[tuple[bytes, list[tuple[Message, ...]]]] = []

    def on(self, prefix: bytes, *replies: Message) -> None:
        for p, sets in self._rules:
            if p == prefix:
                sets.append(replies)
                return
        self._rules.append((prefix, [replies]))

    def push(self, msg: Message) -> None:
        """Inject an unsolicited message."""
        self._put(msg)

    def send(self, msg: Message) -> None:
        if self.closed:
            raise ConnectionError("transport is closed")
        self.sent.append(msg)
        if not isinstance(msg, SysexMessage):
            return
        for prefix, sets in self._rules:
            if msg.data.startswith(prefix) and sets:
                for reply in sets.pop(0):
                    self._put(reply)
                return

    def close(self) -> None:
        self.closed = True
