"""Transport-level message types, independent of mido."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SysexMessage:
    """A SysEx message without the leading F0 and trailing F7 (mido convention)."""

    data: bytes


@dataclass(frozen=True)
class ControlChange:
    control: int
    value: int
    channel: int = 0


@dataclass(frozen=True)
class ProgramChange:
    program: int
    channel: int = 0


Message = SysexMessage | ControlChange | ProgramChange


@dataclass(frozen=True)
class TunerReading:
    """Latest tuner state, emitted whenever a tuner CC (98 note, 99 cents) arrives.

    note is None when the pedal reports "no note"; offset is -7..+7 around 0 (in tune).
    """

    note: str | None
    offset: int
