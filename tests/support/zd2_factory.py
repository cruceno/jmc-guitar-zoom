"""Synthetic ``.ZD2`` effect files for the tests: valid containers with no Zoom DSP code in them.

A real ``.ZD2`` is Zoom's property (it holds compiled DSP code), so the repository does not carry any. The
catalog reads only the container fields below, so a file built here is enough for every test that is not about
Zoom's own bytes (those are marked ``zoom_files`` and read the files ``scripts/fetch_test_fixtures.py`` downloads).

Layout written here, matching ``zoomzt2.ZD2`` and ``jmc_guitar_zoom.effects.catalog``::

    "ZDLF" | length u32 | checksum u32 | target u32 | 73 unknown bytes
    version (4, ASCII) | 00 00 | group u8 | effect id u32 LE | name (11, NUL padded) | group name (11)
    3 unknown bytes | 00 00 00
    ICON | TXJ1 | TXE1 (description) | INFO (dsp load, float) | DATA | PRME (JSON, optional) | 16 trailing bytes

``DATA`` carries the parameter table the catalog reads: 56-byte records ``name(12) | max u32 | default u32 | 36
unused``, ``OnOff`` first, then the effect's own name (max 0xFFFFFFFF), then one record per parameter and one
``Dummy`` record per extra chain slot of a wide effect. ``size`` pads ``DATA`` with zeros so a file keeps the byte
size the tests rely on (the unused-effects test orders by size, the memory tests add the free space to it).
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

GROUPS = {"DYNAMICS": 1, "FILTER": 2, "DRIVE": 3, "AMP": 4, "CABINET": 5, "MODULATION": 6, "SFX": 7, "DELAY": 8,
          "REVERB": 9, "PEDAL": 11, "AG MODEL": 20}
_RECORD = 56


@dataclass(frozen=True)
class Param:
    name: str
    max: int
    default: int
    explanation: str = ""


@dataclass(frozen=True)
class Effect:
    effect_id: int
    name: str
    group: str
    version: str
    dsp_load: float  # the raw INFO value; the catalog shows it divided by 2.5
    description: str
    params: tuple[Param, ...]
    dummies: int = 0  # extra chain slots (a wide effect)
    size: int = 0  # total file size to reach with zero padding (0: no padding)
    prme: str = "json"  # "json" (valid), "invalid" (present but not JSON) or "none" (no PRME chunk)
    extra: dict = field(default_factory=dict)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack("<I", len(payload)) + payload


def _padded(text: str, size: int) -> bytes:
    raw = text.encode("ascii")
    assert len(raw) < size
    return raw.ljust(size, b"\x00")


def _record(name: str, maximum: int, default: int) -> bytes:
    return _padded(name, 12) + struct.pack("<II", maximum, default) + b"\x00" * (_RECORD - 20)


def _table(effect: Effect) -> bytes:
    rows = [_record("OnOff", 1, 1), _record(effect.name, 0xFFFFFFFF, 0)]
    rows += [_record(p.name, p.max, p.default) for p in effect.params]
    rows += [_record("Dummy", 0, 0)] * effect.dummies
    return b"".join(rows) + b"\x00" * _RECORD  # an empty name ends the table


def build_zd2(effect: Effect) -> bytes:
    """The bytes of ``effect`` as a ``.ZD2``; ``zoomzt2.ZD2`` parses them and ``load_zd2`` reads them back."""
    prefix = _table(effect)
    header = (b"\x00" * 16 + _padded("synthetic test effect", 24))  # stands in for the DSP image before the table
    body = {"json": json.dumps({"Parameters": [{"name": p.name, "explanation": p.explanation} for p in effect.params]},
                               indent=1).encode("ascii"),
            "invalid": b"{ not json", "none": b""}[effect.prme]
    tail = b"\x00" * 16

    def assemble(pad: int) -> bytes:
        data = header + prefix + b"\x00" * pad
        info = struct.pack("<f", effect.dsp_load)
        text = effect.description.encode("ascii")
        text += b"\x00" * (-len(text) % 4)
        chunks = (_chunk(b"ICON", b"\x00" * 8) + _chunk(b"TXJ1", b"\x00" * 4) + _chunk(b"TXE1", text)
                  + _chunk(b"INFO", info) + _chunk(b"DATA", data))
        if effect.prme != "none":
            chunks += _chunk(b"PRME", body)
        top = (struct.pack("<I", 0) + struct.pack("<I", 0x100) + b"\x00" * 73
               + effect.version.encode("ascii") + b"\x00\x00" + bytes([GROUPS[effect.group]])
               + struct.pack("<I", effect.effect_id) + _padded(effect.name, 11) + _padded(effect.group, 11)
               + b"\x00" * 3 + b"\x00\x00\x00")
        payload = top + chunks + tail
        return b"ZDLF" + struct.pack("<I", len(payload) + 8) + payload

    out = assemble(0)
    if effect.size > len(out):
        out = assemble(effect.size - len(out))
    return out


def _p(name, maximum, default, explanation=""):
    return Param(name, maximum, default, explanation)


# The effects the tests use. Ids, names, groups, versions and parameter ranges follow what the catalog reads from
# the real files (they are what a patch refers to); the sentences are original text, except the ones that already
# exist in ``jmc_guitar_zoom/effects/descriptions_es.json`` so the Spanish lookup is exercised.
_VOL = "Adjusts the volume."
EFFECTS: dict[str, Effect] = {e.name: e for e in (
    Effect(0x1000010, "Comp", "DYNAMICS", "1.40", 13.94, "A simple compressor in the style of the Dyna Comp.",
           (_p("Sense", 10, 6, "Adjusts the sensitivity of the effect."), _p("ATTCK", 1, 0, "Sets the attack."),
            _p("Tone", 10, 6, "Adjusts the tone."), _p("VOL", 100, 80, _VOL)), size=13390),
    Effect(0x400002C, "FD DLXR", "AMP", "1.10", 77.51, "A clean combo amp with a tremolo.",
           (_p("Input", 1, 0, "Selects the input channel."), _p("Bass", 90, 33, "Adjusts volume of low frequencies."),
            _p("Treble", 90, 55, "Adjusts volume of high frequencies."), _p("Gain", 90, 50, "Adjusts the gain."),
            _p("VOL", 90, 90, _VOL), _p("Depth", 90, 0, "Sets the depth of the tremolo."),
            _p("Speed", 100, 40, "Sets the speed of the tremolo.")), dummies=2, size=44154),
    Effect(0x2000054, "Gt GEQ 7", "FILTER", "1.20", 14.35, "A seven-band graphic equaliser.",
           tuple(_p(band, 48, 24, f"Boosts or cuts the {band} band.") for band in
                 ("100", "200", "400", "800", "1.6k", "3.2k", "6.4k")) + (_p("VOL", 100, 80, _VOL),),
           dummies=1, size=17772),
    Effect(0x9000030, "Hall", "REVERB", "1.50", 27.08, "A large hall reverb.",
           (_p("PreD", 99, 48, "Adjusts the delay before the reverb."), _p("Decay", 29, 9, "Sets the duration of the reverb."),
            _p("Mix", 100, 46, "Adjusts the amount of effect sound."), _p("Tail", 1, 0, "Lets the tail ring out when ON.")),
           size=17933),
    Effect(0x1000020, "RackComp", "DYNAMICS", "1.40", 18.25, "A rack compressor.",
           (_p("THRSH", 60, 38), _p("Ratio", 90, 30), _p("Knee", 1, 1), _p("VOL", 100, 80)),
           size=45595, prme="invalid"),
    Effect(0x1800030, "160 Comp", "DYNAMICS", "1.40", 31.58, "A compressor with a threshold and a ratio.",
           (_p("THRSH", 60, 38, "Adjusts the threshold."), _p("Ratio", 90, 30, "Adjusts the compression ratio."),
            _p("Knee", 1, 1, "Sets the type of knee."), _p("VOL", 100, 80, _VOL)), size=15903),
    Effect(0x14400190, "12Strings", "AG MODEL", "1.00", 77.1, "A twelve-string acoustic model.",
           (_p("Gain", 48, 24, "Adjusts the gain."), _p("Bass", 100, 50, "Adjusts volume of low frequencies."),
            _p("MID", 100, 50, "Adjusts volume of middle frequencies."),
            _p("Treble", 100, 50, "Adjusts volume of high frequencies.")), size=27864),
    Effect(0x500002A, "FD-DX1x12", "CABINET", "1.40", 22.1, "A 1x12 combo cabinet with two microphones.",
           (_p("MIC", 1, 0, "Chooses the microphone position."), _p("D57:D421", 100, 50, "Balances the two microphones."),
            _p("Hi", 100, 50, "Adjusts volume of high frequencies."), _p("Lo", 100, 50, "Adjusts volume of low frequencies.")),
           size=32994),
    Effect(0x1000080, "OptComp", "DYNAMICS", "1.50", 31.8, "An optical compressor.",
           (_p("Drive", 10, 7, "Adjusts the depth of the compression."), _p("Lo", 100, 50, "Adjusts volume of low frequencies."),
            _p("Hi", 100, 50, "Adjusts volume of high frequencies."), _p("VOL", 100, 60, _VOL)), size=14380),
)}

# the ZD2 file names they carry on the pedal (``flst.pedal_filename`` of the catalog name)
PEDAL_FILES = {"Comp": "COMP.ZD2", "FD DLXR": "FDDLXR1U.ZD2", "Gt GEQ 7": "GTGEQ71U.ZD2", "Hall": "HALL.ZD2",
               "RackComp": "RACKCOMP.ZD2", "FD-DX1x12": "FDDX1X12.ZD2", "OptComp": "OPTCOMP.ZD2"}
