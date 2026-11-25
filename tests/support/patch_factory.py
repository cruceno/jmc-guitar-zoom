"""Synthetic ``.zptc`` patches for the tests, built with the product's own ``build_zptc``.

The repository carries no patch dumped from a pedal (factory patches are Zoom's, the user's own are personal).
Each patch here is a chain of effect ids and parameters chosen for the tests; the ids are the ones of the
synthetic catalog (``zd2_factory``) or of effects the catalog does not hold, as the tests need. ``HB_JAZZ`` is the
five-effect patch the editor tests use (OptComp, FD DLXR, FD-DX1x12, Gt GEQ 7, Hall; the pedal inserts a filler
slot after each of the two wide effects, so the buffer holds seven slots).

Hardware observations kept as synthetic cases:

* the pedal pads a name it wrote to 10 characters with spaces (``name_raw``), and ends a description with a
  newline; a patch saved by the app has neither, and a rebuild must keep whichever it was given (``ACOUSTIC_A``
  has the pedal's form, ``HB_JAZZ`` the app's);
* the pedal stores bits and bytes of each effect record and of the header that this app does not understand
  (``unknown_bytes``, ``unknown_bits``, ``header_data``, the ``pprm`` fields); ``quirky_patch`` sets them all and
  the round-trip tests require they survive a parse and a rebuild.
"""
from __future__ import annotations

from pathlib import Path

from zoomstudio.patches.model import EffectSlot, Patch
from zoomstudio.patches.zptc import build_zptc

_PPRM = ("byte00", "byte01", "byte02", "byte03", "byte04", "byte05", "byte06", "byte07", "editSlot", "byte09",
         "byte10", "byte11")
FILLER = 0x1  # the pedal's filler slot after a wide effect


def slot(effect_id: int, *params: int, enabled: bool = True) -> EffectSlot:
    return EffectSlot(effect_id=effect_id, enabled=enabled, params=list(params) + [0] * (12 - len(params)))


def patch(name: str, slots: list[EffectSlot], description: str = "", volume: int = 100, *, pedal_style: bool = False,
          edit_slot: int = 0) -> bytes:
    """A 760-byte buffer. ``pedal_style`` pads the name with spaces and gives the description the pedal's form."""
    pprm = {key: 0 for key in _PPRM}
    pprm["editSlot"] = edit_slot
    txt = description.encode("ascii")
    model = Patch(name=name, volume=volume, description=description, effects=slots,
                  name_raw=name.ljust(10) if pedal_style else name, desc_raw=description,
                  txj1_data=txt + b"\x00" * (-len(txt) % 4), pprm=pprm)
    return build_zptc(model)


ACOUSTIC_A = patch("Acoustic A", [slot(0x14400000, 24, 50, 50, 50), slot(0x1000080, 3, 50, 50, 50),
                                  slot(0x2400040, 21, 20, 20, 22, 0, 20, 0, 65), slot(FILLER), slot(0x9000070, 49, 35, 30),
                                  slot(0)], "An acoustic guitar sound for the tests.\n", pedal_style=True)
ACOUSTIC_B = patch("Acoustic B", [slot(0x144000A0, 24, 50, 50, 50), slot(0x1000020, 9, 1, 4, 50),
                                  slot(0x2400040, 20, 20, 22, 22, 1, 20, 0, 81), slot(FILLER), slot(0x9000030, 19, 12, 49),
                                  slot(0)], "A dry strumming sound for the tests.\n", volume=110, pedal_style=True)
UNPLUGGED = patch("AG ECunplg", [slot(0x14400040, 24, 50, 50, 50), slot(0x1000020, 12, 2, 3, 62),
                                 slot(0x2400040, 19, 20, 19, 22, 1, 11, 0, 75), slot(FILLER), slot(0x9000070, 73, 35, 30),
                                 slot(0)], "A light sound for playing with a band.\n", pedal_style=True)
DLYVERB = patch("AG DlyVerb", [slot(0x14400130, 24, 50, 45, 50), slot(0x6400000, 8, 30, 60, 55),
                               slot(0x8400000, 415, 37, 60, 1), slot(0x8000081, 849, 30, 50, 1),
                               slot(0x9000070, 24, 45, 60, 1)], "Two delays and a reverb for the tests.\n",
                pedal_style=True, edit_slot=3)
EMPTY = patch("Empty", [slot(0)] * 5, pedal_style=True)

_HB_CHAIN = [(0x1000080, [4, 55, 42, 62]), (0x400002C, [0, 42, 28, 38, 75, 0, 40]), (0x500002A, [0, 70, 35, 55]),
             (0x2000054, [23, 25, 26, 24, 23, 20, 19, 80]), (0x9000030, [20, 11, 24, 1])]
_HB_TEXT = "Warm jazz box for hollow body: OptComp, FD Deluxe Reverb, 1x12 cab, GEQ7, Hall."
HB_SENT = patch("HB Jazz", [slot(i, *p) for i, p in _HB_CHAIN], _HB_TEXT)  # the form the app sends: no fillers
HB_JAZZ = patch("HB Jazz", [slot(0x1000080, 4, 55, 42, 62), slot(0x400002C, 0, 42, 28, 38, 75, 0, 40), slot(FILLER),
                            slot(0x500002A, 0, 70, 35, 55), slot(0x2000054, 23, 25, 26, 24, 23, 20, 19, 80),
                            slot(FILLER), slot(0x9000030, 20, 11, 24, 1)], _HB_TEXT)

# the pedal's backup of its first slots, as the librarian tests load them: slot 1, 2, 3 and 44
BACKUP = {1: ACOUSTIC_A, 2: ACOUSTIC_B, 3: UNPLUGGED, 44: HB_JAZZ}


def quirky_patch() -> bytes:
    """A buffer with every field this app does not interpret set to a non-zero value."""
    model = Patch(name="Quirks", volume=64, description="odd fields\n", effects=[
        EffectSlot(0x1000010, True, [1] * 12, unknown_bytes=b"\x12\x34\x56", unknown_bits=0b101010),
        EffectSlot(0x9000030, False, [2] * 12, unknown_bytes=b"\xff\x00\x01", unknown_bits=0b000011)],
        header_data=b"\x01\x02\x03\x04\x05\x06", name_raw="Quirks    ", desc_raw="odd fields\n",
        txj1_data=b"odd\x00", pprm={key: 1 for key in _PPRM})
    return build_zptc(model)


def write_backup(folder: Path) -> Path:
    """``001.zptc``, ``002.zptc``, ``003.zptc`` and ``044.zptc`` in ``folder``, as the librarian names a backup."""
    folder.mkdir(parents=True, exist_ok=True)
    for number, data in BACKUP.items():
        (folder / f"{number:03d}.zptc").write_bytes(data)
    return folder
