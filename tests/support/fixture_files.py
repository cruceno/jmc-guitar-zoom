"""The files the tests read, generated once per run into a temporary folder.

Nothing Zoom-proprietary is committed (see the docstrings of the factories next to this module), so the
folders the tests used to read from ``tests/*/fixtures`` are written here from the factories:

* ``EFFECTS``: ``COMP.ZD2`` and four more effects, ``lib/`` (a Guitar Lab style cache: ``160_COMP_140.zd2``,
  ``MDL_12ST_100.zd2``, ``lib/SVG``), ``AllZDL7_2.lst``;
* ``UI``: ``catalog/`` (six effects and their ``SVG``), ``backup/`` (four patches named like a pedal backup),
  ``53-HB-Jazz.zptc``, ``AllZDL7_2.lst``;
* ``PATCHES``: five patches; ``DEVICE``: ``001.zptc``.

Tests that need Zoom's real files read ``ZOOM_FILES`` instead (``scripts/fetch_test_fixtures.py`` fills it) and
carry the ``zoom_files`` marker.
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
import zlib
from pathlib import Path

import lst_factory
import patch_factory as pf
import zd2_factory as zf

ZOOM_FILES = Path(__file__).resolve().parents[1] / ".zoom-fixtures"  # git-ignored; filled by the fetch script


def have_zoom_files() -> bool:
    return (ZOOM_FILES / "effects" / "AllZDL7_2.lst").is_file() and any((ZOOM_FILES / "effects").glob("*.zd2"))


def svg(name: str) -> str:
    """A small original artwork: a rounded box with a coloured knob, in the 68x96 box real effect art uses."""
    hue = zlib.crc32(name.encode()) % 360
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 68 96"><rect x="4" y="4" width="60" height="88" '
            f'rx="8" fill="#3a3a3a"/><circle cx="34" cy="38" r="14" fill="hsl({hue},70%,55%)"/>'
            f'<rect x="14" y="68" width="40" height="8" rx="3" fill="#bbbbbb"/></svg>\n')


def _effect_file(folder: Path, effect_name: str, file_name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file_name).write_bytes(zf.build_zd2(zf.EFFECTS[effect_name]))


def _write(root: Path) -> None:
    lst = lst_factory.build_lst()
    effects, ui, patches, device = (root / n for n in ("effects", "ui", "patches", "device"))
    for name in ("Comp", "FD DLXR", "Gt GEQ 7", "Hall", "RackComp"):
        _effect_file(effects, name, zf.PEDAL_FILES[name])
    _effect_file(effects / "lib", "160 Comp", "160_COMP_140.zd2")
    _effect_file(effects / "lib", "12Strings", "MDL_12ST_100.zd2")
    (effects / "lib" / "SVG").mkdir(parents=True)
    (effects / "lib" / "SVG" / "160_COMP.svg").write_text(svg("160_COMP"), encoding="utf-8")
    (effects / "AllZDL7_2.lst").write_bytes(lst)

    for name in ("Comp", "FD DLXR", "FD-DX1x12", "Gt GEQ 7", "Hall", "OptComp"):
        file_name = zf.PEDAL_FILES[name]
        _effect_file(ui / "catalog", name, file_name)
        if name != "FD DLXR":  # the amp has no artwork: the tiles must cope with a missing one
            (ui / "catalog" / "SVG").mkdir(exist_ok=True)
            (ui / "catalog" / "SVG" / f"{file_name[:-4]}.svg").write_text(svg(file_name), encoding="utf-8")
    pf.write_backup(ui / "backup")
    (ui / "53-HB-Jazz.zptc").write_bytes(pf.HB_JAZZ)
    (ui / "AllZDL7_2.lst").write_bytes(lst)

    patches.mkdir(parents=True)
    for file_name, data in (("001.zptc", pf.ACOUSTIC_A), ("019.zptc", pf.DLYVERB), ("041.zptc", pf.EMPTY),
                            ("53-HB-Jazz.zptc", pf.HB_JAZZ), ("53-HB-Jazz.sent.zptc", pf.HB_SENT)):
        (patches / file_name).write_bytes(data)
    device.mkdir(parents=True)
    (device / "001.zptc").write_bytes(pf.ACOUSTIC_A)


ROOT = Path(tempfile.mkdtemp(prefix="jmc_guitar_zoom-fixtures-"))
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)
_write(ROOT)
EFFECTS, UI, PATCHES, DEVICE = (ROOT / n for n in ("effects", "ui", "patches", "device"))
