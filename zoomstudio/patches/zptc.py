"""Parse and build Zoom A1 FOUR ``.zptc`` patch buffers (ZPTC version 1).

Reuses the construct definitions of ``decode_preset`` (upstream, untouched).
"""
from __future__ import annotations

import decode_preset as d

from .model import EffectSlot, Patch

PATCH_BUFFER_SIZE = 760  # size of the buffer the pedal reads and writes

_PPRM_FIELDS = (
    "byte00", "byte01", "byte02", "byte03", "byte04", "byte05", "byte06", "byte07",
    "editSlot", "byte09", "byte10", "byte11",
)


def parse_zptc(data: bytes) -> Patch:
    """Decode a patch buffer (any length >= the logical length) into a ``Patch``."""
    try:
        cfg = d.ZPTC.parse(bytes(data))
    except Exception as exc:  # construct raises several error types
        raise ValueError(f"not a valid ZPTC patch: {exc}") from exc
    if cfg.version != 1:
        raise ValueError(f"unsupported ZPTC version {cfg.version}")

    slots = []
    for ident, fx in zip(cfg.ids, cfg.EDTB.effects):
        rev = fx.reversed
        bw = rev.bitwise
        slots.append(
            EffectSlot(
                effect_id=int(ident),
                enabled=bool(bw.enabled),
                params=[int(bw["param%d" % n]) for n in range(1, 13)],
                unknown_bytes=bytes(rev.unknown),
                unknown_bits=int(bw.unknown),
            )
        )

    pprm = cfg.PPRM.reversed.bitwise
    name_raw = str(cfg.name)
    return Patch(
        name=name_raw.rstrip(" \x00"),
        volume=int(pprm.patchVolume),
        description=str(cfg.TXE1.desc),
        effects=slots,
        version=int(cfg.version),
        target=int(cfg.target),
        header_data=bytes(cfg.data),
        name_raw=name_raw,
        desc_raw=str(cfg.TXE1.desc),
        txj1_data=bytes(cfg.TXJ1.data),
        pprm={k: int(pprm[k]) for k in _PPRM_FIELDS},
    )


def build_zptc(patch: Patch) -> bytes:
    """Encode ``patch`` into exactly 760 bytes (logical content + zero padding)."""
    patch.validate()
    # Start from an empty template and fill every field (no state shared with callers).
    cfg = d.ZPTC.parse(_TEMPLATE)
    n = len(patch.effects)

    cfg.target = patch.target
    cfg.data = patch.header_data
    if patch.name == patch.name_raw.rstrip(" \x00"):
        cfg.name = patch.name_raw  # untouched: keep the pedal's own padding
    else:
        cfg.name = patch.name
    cfg.ids = [s.effect_id for s in patch.effects]
    cfg.fx_count = n

    effects = []
    for slot in patch.effects:
        fx = d.Container()
        rev = d.Container()
        rev.unknown = slot.unknown_bytes
        bw = d.Container()
        bw.unknown = slot.unknown_bits
        for i, v in enumerate(slot.params, start=1):
            bw["param%d" % i] = v
        bw.id = slot.effect_id & 0x1FFFFFFF
        bw.enabled = slot.enabled
        rev.bitwise = bw
        fx.reversed = rev
        fx.autorev = d.EDTB2.build(rev)
        effects.append(fx)
    cfg.EDTB.effects = effects

    pprm = cfg.PPRM.reversed.bitwise
    for k, v in patch.pprm.items():
        pprm[k] = v
    pprm.patchVolume = patch.volume
    cfg.PPRM.autorev = d.PPRM_rev.build(cfg.PPRM.reversed)

    cfg.TXE1.desc = patch.description
    if patch.description == patch.desc_raw:
        cfg.TXJ1.data = patch.txj1_data
    else:
        txt = patch.description.encode("ascii")
        cfg.TXJ1.data = txt + b"\x00" * (-len(txt) % 4) if txt else b""

    blob = d.ZPTC.build(cfg)
    blob = d.ZPTC.build(d.ZPTC.parse(blob))  # second pass fixes the length field
    blob = _trim_exact_description(blob, n, len(cfg.TXJ1.data), len(patch.description))
    if len(blob) > PATCH_BUFFER_SIZE:
        raise ValueError(f"patch is {len(blob)} bytes, the pedal buffer holds {PATCH_BUFFER_SIZE}")
    return blob + b"\x00" * (PATCH_BUFFER_SIZE - len(blob))


def _trim_exact_description(blob: bytes, fx_count: int, txj1_len: int, desc_len: int) -> bytes:
    """Undo construct's forced NUL terminator when the description fills whole words.

    The pedal pads the TXE1 text to a multiple of 4 *without* adding a terminator
    (length 0 for an empty text, 44 for 44 chars), whereas decode_preset's rebuild
    always adds 4 bytes in that case. Strip them so the output matches the pedal.
    """
    if desc_len % 4:
        return blob
    off = 36 + 4 * fx_count + 8 + txj1_len  # offset of the TXE1 tag
    assert blob[off : off + 4] == b"TXE1"
    end = off + 8 + desc_len
    out = bytearray(blob[:end] + blob[end + 4 :])
    out[off + 4 : off + 8] = desc_len.to_bytes(4, "little")
    total = int.from_bytes(out[4:8], "little") - 4
    out[4:8] = total.to_bytes(4, "little")
    return bytes(out)


def _make_template() -> bytes:
    """Minimal valid version-1 ZPTC with a single empty slot, used as construct scaffold."""
    import pathlib

    raw = (pathlib.Path(__file__).with_name("template.zptc")).read_bytes()
    return raw


_TEMPLATE = _make_template()
