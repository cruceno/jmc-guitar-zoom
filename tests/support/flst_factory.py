"""A synthetic ``FLST_SEQ.ZT2``: the effect list of an A1 FOUR, built from the layout observed on the pedal.

The real file belongs to the user's pedal and lists Zoom's whole catalogue, so the repository carries none. The
layout, as ``jmc_guitar_zoom/effects/flst.py`` documents it (fw 1.01):

* the file is 14,784 bytes: the lists, then zero padding;
* two sections (the pedal keeps two copies of the list), each a run of groups;
* a group is framed by ``>>> 00 <group>`` and ``<<< 00 <group>``, each frame padded with zeros to 26 bytes;
* every section starts with a group 0 holding the ``BYPASS.ZD2`` record;
* a record is 26 bytes: the file name NUL-padded to 12, ``00``, the version (4 ASCII bytes), ``00``, the installed
  flag (0 or 1), the effect id (4 bytes, little endian) and ``00 00 00``.

Hardware observation the tests encode: installing 12Strings with Guitar Lab changed exactly one byte, the flag of
the ``MDL_12ST.ZD2`` record of the first section; the second section already had it set, so ``flst.is_installed``
must read the first section only. ``build_flst(installed_12st=...)`` makes the two states, ``BEFORE`` and ``AFTER``.
"""
from __future__ import annotations

import struct

TOTAL_SIZE = 14_784
RECORD_SIZE = 26

# (group id, [(file name, version, id, installed before the 12Strings install)])
LIST: list[tuple[int, list[tuple[str, str, int, bool]]]] = [
    (0, [("BYPASS.ZD2", "\x00\x00\x00\x00", 0x00000000, True)]),
    (1, [("COMP.ZD2", "1.40", 0x01000010, True), ("RACKCOMP.ZD2", "1.40", 0x01000020, True),
         ("OPTCOMP.ZD2", "1.50", 0x01000080, True), ("BLACKOPT.ZD2", "1.00", 0x01000090, False),
         ("160_COMP.ZD2", "1.40", 0x01800030, False)]),
    (2, [("GTGEQ71U.ZD2", "1.20", 0x02000054, True), ("PARAEQ2.ZD2", "1.00", 0x02000064, False),
         ("B_ATWAH.ZD2", "1.40", 0x02800010, False)]),
    (4, [("FDDLXR1U.ZD2", "1.10", 0x0400002C, True)]),
    (5, [("FDDX1X12.ZD2", "1.40", 0x0500002A, True)]),
    (6, [("B_OCTAVE.ZD2", "1.40", 0x06800050, True)]),
    (9, [("HALL.ZD2", "1.50", 0x09000030, True), ("CHURCH.ZD2", "1.00", 0x09000040, False)]),
    (20, [("MDL_12ST.ZD2", "1.00", 0x14400190, False), ("MDL_UPBS.ZD2", "1.00", 0x14400180, False)]),
]
TWELVE_STRINGS = "MDL_12ST.ZD2"


def _frame(opening: bool, group: int) -> bytes:
    return (b">>>" if opening else b"<<<") + b"\x00" + bytes([group]) + b"\x00" * 21


def _record(name: str, version: str, effect_id: int, installed: bool) -> bytes:
    field = name.encode("ascii").ljust(12, b"\x00")
    out = field + b"\x00" + version.encode("latin-1") + b"\x00" + bytes([int(installed)]) + struct.pack("<I", effect_id)
    return out + b"\x00\x00\x00"


def _section(flag_of_12st: bool) -> bytes:
    out = b""
    for group, records in LIST:
        out += _frame(True, group)
        for name, version, effect_id, installed in records:
            out += _record(name, version, effect_id, flag_of_12st if name == TWELVE_STRINGS else installed)
        out += _frame(False, group)
    return out


def build_flst(installed_12st: bool = False) -> bytes:
    """The list with the 12Strings flag of the first section set or clear; the second section always has it set."""
    data = _section(installed_12st) + _section(True)
    assert len(data) <= TOTAL_SIZE
    return data.ljust(TOTAL_SIZE, b"\x00")


BEFORE = build_flst(False)  # 12Strings not installed
AFTER = build_flst(True)  # the same pedal after Guitar Lab installed it
