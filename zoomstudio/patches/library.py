"""Folder-level operations of the librarian: backups, exports and imports of ``.zptc`` files.

Pure file helpers (no Qt, no MIDI). A folder is never overwritten: every writer creates its
folder exclusively and every file with ``xb``.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .model import Patch
from .zptc import build_zptc, parse_zptc

EMPTY_PATCH_FILE = Path(__file__).with_name("empty.zptc")  # the factory "Empty" patch (backup slot 41)
_PATCH_FILE = re.compile(r"^(\d+)(?:-.*)?\.zptc$", re.IGNORECASE)


def empty_patch() -> Patch:
    """A fresh copy of the factory "Empty" patch."""
    return parse_zptc(EMPTY_PATCH_FILE.read_bytes())


def timestamp(now: str | None = None) -> str:
    return now or time.strftime("%Y%m%d-%H%M%S")


def new_folder(parent: Path, prefix: str, now: str | None = None) -> Path:
    """Create ``<parent>/<prefix>-<timestamp>``; raise ``FileExistsError`` if it already exists."""
    folder = Path(parent) / f"{prefix}-{timestamp(now)}"
    Path(parent).mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=False)
    return folder


def safe_file_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or "patch"


def write_new(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)


def write_manifest(folder: Path, manifest: dict) -> None:
    (Path(folder) / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def export_patches(folder: Path, patches: dict[int, Patch], now: str | None = None) -> Path:
    """Write ``NNN.zptc`` per patch plus a manifest into a new ``export-<timestamp>`` folder."""
    dest = new_folder(folder, "export", now)
    entries = []
    for location in sorted(patches):
        name = f"{location:03d}.zptc"
        data = build_zptc(patches[location])
        write_new(dest / name, data)
        entries.append({"location": location, "file": name, "bytes": len(data), "name": patches[location].name})
    write_manifest(dest, {"created": timestamp(now), "patches": entries})
    return dest


def export_one(folder: Path, location: int, patch: Patch) -> Path:
    """Write one patch as ``NNN-<name>.zptc`` (never overwrites)."""
    path = Path(folder) / f"{location:03d}-{safe_file_name(patch.name or 'patch')}.zptc"
    write_new(path, build_zptc(patch))
    return path


def read_folder(folder: Path) -> tuple[dict[int, Patch], list[str]]:
    """Parse the ``NNN.zptc`` / ``NNN-name.zptc`` files of a folder; returns patches and problems."""
    found: dict[int, Patch] = {}
    problems: list[str] = []
    for path in sorted(Path(folder).iterdir()):
        m = _PATCH_FILE.match(path.name)
        if not m:
            continue
        try:
            found[int(m.group(1))] = parse_zptc(path.read_bytes())
        except (ValueError, OSError) as exc:
            problems.append(f"{path.name}: {exc}")
    return found, problems
