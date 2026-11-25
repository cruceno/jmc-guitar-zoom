"""Effect catalog: metadata read from Zoom ``.ZD2`` effect files.

The file container is parsed with the upstream ``zoomzt2.ZD2`` construct
(imported, never modified). Parameter ranges and defaults are not described
by the container itself: they live in a table inside the DSP ELF stored in
the ``DATA`` chunk. The table starts at the ``OnOff`` record and is made of
56-byte records::

    name (12 bytes, NUL padded) | max u32 LE | default u32 LE | 40 bytes unused

Record 0 is ``OnOff``, record 1 carries the effect's own name (max
0xFFFFFFFF), then one record per parameter. Trailing ``Dummy`` records are
paging fillers of wide (two chain slots) effects.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

import zoomzt2

_RECORD_SIZE = 56
_ONOFF_MARKER = b"OnOff\x00"
_DUMMY = "Dummy"
# Zoom reports DSP load as a value where 100 % of the chip is 250.
_DSP_LOAD_DIVISOR = 2.5
# Guitar Lab caches an effect as NAME_VVV.zd2 (lowercase extension, three-digit version);
# the pedal stores it as NAME.ZD2, and NAME itself may end in digits (MDL_314.ZD2 is 314ce).
_GUITAR_LAB_NAME = re.compile(r"^(?P<stem>.+)_\d{3}\.zd2$")


@dataclass(frozen=True)
class ParamInfo:
    name: str
    explanation: str
    max: int
    default: int


@dataclass
class EffectInfo:
    effect_id: int
    filename: str
    name: str
    group: str
    version: str
    dsp_load_percent: float
    description: str
    params: list[ParamInfo] = field(default_factory=list)
    is_wide: bool = False
    dummy_count: int = 0
    svg_path: Path | None = None
    path: Path | None = None
    sources: list[str] = field(default_factory=list)

    @property
    def slots(self) -> int:
        """Number of chain slots the effect occupies on the pedal."""
        return 2 if self.is_wide else 1


def _parse_records(data: bytes) -> list[tuple[str, int, int]]:
    """Read the (name, max, default) table of a DSP ELF, OnOff first."""
    pos = data.find(_ONOFF_MARKER)
    records: list[tuple[str, int, int]] = []
    while pos >= 0 and pos + _RECORD_SIZE <= len(data):
        raw = data[pos : pos + 12]
        name = raw.split(b"\x00", 1)[0]
        if (
            not name
            or not all(32 <= c < 127 for c in name)
            or any(raw[len(name) :])
        ):
            break
        max_, default = struct.unpack_from("<II", data, pos + 12)
        records.append((name.decode("ascii"), max_, default))
        pos += _RECORD_SIZE
    return records


def _prme_entries(prme) -> list[dict]:
    if prme is None:
        return []
    try:
        doc = json.loads(prme.xml, strict=False)
        return list(doc["Parameters"])
    except (ValueError, KeyError, TypeError):
        return []


def svg_stem(filename: str) -> str:
    """Effect name without Guitar Lab's version: ``160_COMP_140.zd2`` -> ``160_COMP``, ``MDL_314.ZD2`` -> ``MDL_314``."""
    name = Path(filename).name
    match = _GUITAR_LAB_NAME.match(name)
    return match["stem"] if match else Path(name).stem


def find_svg(filename: str, svg_dir: Path | None) -> Path | None:
    if svg_dir is None:
        return None
    candidate = Path(svg_dir) / f"{svg_stem(filename)}.svg"
    return candidate if candidate.is_file() else None


def load_zd2(path: str | Path, svg_dir: str | Path | None = None) -> EffectInfo:
    path = Path(path)
    zd2 = zoomzt2.ZD2.parse_file(str(path))
    records = _parse_records(zd2.DATA.data) if zd2.DATA is not None else []
    table = records[2:]  # skip OnOff and the effect-name record
    dummy_count = sum(1 for r in table if r[0] == _DUMMY)
    real = [r for r in table if r[0] != _DUMMY]
    entries = _prme_entries(zd2.PRME)

    params = []
    for i, (name, max_, default) in enumerate(real):
        entry = entries[i] if i < len(entries) else {}
        params.append(
            ParamInfo(
                name=entry.get("name") or name,
                explanation=(entry.get("explanation") or "").strip(),
                max=max_,
                default=default,
            )
        )

    return EffectInfo(
        effect_id=zd2.id,
        filename=path.name,
        name=zd2.name,
        group=zd2.groupname,
        version=zd2.version,
        dsp_load_percent=zd2.INFO.dspload / _DSP_LOAD_DIVISOR,
        description=zd2.TXE1.description.strip(),
        params=params,
        is_wide=dummy_count > 0,
        dummy_count=dummy_count,
        svg_path=find_svg(path.name, Path(svg_dir) if svg_dir else None),
        path=path,
    )


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version))


def load_catalog(*dirs, svg_dir: str | Path | None = None) -> dict[int, EffectInfo]:
    """Load every ``*.zd2`` in ``dirs``, keyed by effect ID.

    Each entry of ``dirs`` is a path or a ``(label, path)`` pair; the label
    (default: the path) is recorded in ``EffectInfo.sources`` for every
    directory holding that ID. The higher version wins; ties keep the
    earlier directory. SVGs are looked up in ``svg_dir`` or, by default, in
    ``<dir>/SVG``.
    """
    catalog: dict[int, EffectInfo] = {}
    for entry in dirs:
        label, folder = entry if isinstance(entry, tuple) else (str(entry), entry)
        folder = Path(folder)
        svgs = Path(svg_dir) if svg_dir else folder / "SVG"
        files = sorted(
            p for p in folder.iterdir() if p.suffix.lower() == ".zd2" and p.is_file()
        )
        for file in files:
            info = load_zd2(file, svgs)
            info.sources = [label]
            current = catalog.get(info.effect_id)
            if current is None:
                catalog[info.effect_id] = info
                continue
            sources = list(dict.fromkeys(current.sources + info.sources))
            if _version_key(info.version) > _version_key(current.version):
                info.svg_path = info.svg_path or current.svg_path
                catalog[info.effect_id] = info
                current = info
            else:
                current.svg_path = current.svg_path or info.svg_path
            current.sources = sources
    return catalog


def a1four_effect_ids(lst_path: str | Path, model_id: int = 0x6E001100) -> set[int]:
    """Effect IDs Guitar Lab lists for the A1 FOUR (model ``0x6E001100``)."""
    text = Path(lst_path).read_bytes().decode("utf-8", errors="replace").lstrip()
    doc, _ = json.JSONDecoder().raw_decode(text)  # file has trailing garbage
    for model in doc["models"]:
        if int(model["modelId"], 16) == model_id:
            return {int(e["type"], 16) for e in model["effects"]}
    return set()
