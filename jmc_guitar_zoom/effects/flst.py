"""Read and change the install flags in a pedal's FLST_SEQ.ZT2 without rebuilding it.

Layout observed on an A1 FOUR (fw 1.01): two sections, each a run of groups framed
by ``>>>`` / ``<<<``, and each starting with a ``BYPASS.ZD2`` record. A record is
26 bytes: the file name NUL-padded to 12 bytes, ``00``, a 4-byte version, ``00``,
the installed flag (0 or 1), the effect id (4 bytes) and ``00 00 00``.

Installing 12Strings with Guitar Lab changed exactly one byte: the flag of the
``MDL_12ST.ZD2`` record in the first section (the second section already had it
set). zoomzt2 rebuilds the whole file with a fixed size, which truncates the A1
FOUR's list, so this module only ever flips that one byte in place.
"""
from __future__ import annotations

import re

from .catalog import svg_stem

FLST_NAME = "FLST_SEQ.ZT2"
NAME_FIELD = 12
FLAG_OFFSET = 18
_FIRST_RECORD = b"BYPASS.ZD2".ljust(NAME_FIELD, b"\x00")


class FlstError(ValueError):
    """The list does not have the expected layout or does not list the effect."""


def pedal_filename(filename: str) -> str:
    """Pedal file name of an effect file: ``MDL_12ST_100.zd2`` -> ``MDL_12ST.ZD2``."""
    return f"{svg_stem(filename).upper()}.ZD2"


def _first_section_end(data: bytes) -> int:
    first = data.find(_FIRST_RECORD)
    second = data.find(_FIRST_RECORD, first + 1) if first >= 0 else -1
    if first < 0 or second < 0 or data.find(_FIRST_RECORD, second + 1) >= 0:
        raise FlstError("unrecognised FLST_SEQ layout: expected two sections starting with BYPASS.ZD2")
    return second


def _is_record(data: bytes, at: int) -> bool:
    return (at + 26 <= len(data) and data[at + NAME_FIELD] == 0 and data[at + 17] == 0
            and data[at + FLAG_OFFSET] in (0, 1))


def _records(data: bytes) -> dict[str, int]:
    """Name -> offset of every record in the first section."""
    end = _first_section_end(data)
    found: dict[str, int] = {}
    for match in re.finditer(rb"[A-Z0-9_]{1,8}\.ZD2", data[:end]):
        at = match.start()
        field = data[at:at + NAME_FIELD]
        name = field.rstrip(b"\x00").decode("ascii")
        if field != name.encode().ljust(NAME_FIELD, b"\x00") or not _is_record(data, at):
            continue
        if name in found:
            raise FlstError(f"{name} is listed twice in the first section")
        found[name] = at
    return found


def _record(data: bytes, name: str) -> int:
    at = _records(data).get(name.upper())
    if at is None:
        raise FlstError(f"{name} is not in the pedal's effect list")
    return at


def is_installed(data: bytes, name: str) -> bool:
    return data[_record(data, name) + FLAG_OFFSET] == 1


def installed_names(data: bytes) -> list[str]:
    return [name for name, at in _records(data).items() if data[at + FLAG_OFFSET] == 1]


def set_installed(data: bytes, name: str, installed: bool) -> bytes:
    """Return ``data`` with only the install flag of ``name`` changed."""
    at = _record(data, name) + FLAG_OFFSET
    out = bytearray(data)
    out[at] = 1 if installed else 0
    return bytes(out)
