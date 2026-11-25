"""The patch bank: patches the user took off the pedal and the app keeps (no Qt, no MIDI).

One ``.zptc`` per entry, created exclusively and never overwritten, plus ``index.json`` with what the
file cannot say: where the patch came from and when it was stored. The index is a convenience: when it
is missing or damaged it is rebuilt from the files, so the files alone are enough to lose nothing.
The bank holds patches that are not on the pedal: an entry is removed only by the caller, and only
after the patch was verified written back to the pedal.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .library import safe_file_name, write_new
from .zptc import parse_zptc

INDEX_NAME = "index.json"
INDEX_VERSION = 1


class BankError(Exception):
    """The bank could not store, read or find an entry."""


@dataclass(frozen=True)
class BankEntry:
    id: str  # the file stem: unique inside the folder
    file: str
    name: str
    origin: int | None  # position (as the pedal shows it) the patch came from; None when unknown
    stored_at: str  # YYYYmmdd-HHMMSS
    sha256: str


def default_dir() -> Path:
    from zoomstudio.__main__ import workspace_root  # late: the entry point imports the UI

    return workspace_root() / "patches" / "bank"


def write_exclusive(path: Path, data: bytes) -> None:
    """Create ``path`` with ``data``; raise ``FileExistsError`` if it exists (never overwrites)."""
    write_new(path, data)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PatchBank:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = Path(folder) if folder is not None else default_dir()

    # ------------------------------------------------------------------ queries

    def list(self) -> list[BankEntry]:
        """Entries in storage order (oldest first), reconciled with the files on disk."""
        stored = self._load_index()
        files = {p.name: p for p in sorted(self.folder.glob("*.zptc"))} if self.folder.is_dir() else {}
        entries: list[BankEntry] = [e for e in stored if e.file in files]
        known = {e.file for e in entries}
        for name, path in files.items():
            if name not in known:
                adopted = self._adopt(path)
                if adopted is not None:
                    entries.append(adopted)
        entries.sort(key=lambda e: (e.stored_at, e.id))
        if entries != stored or not (self.folder / INDEX_NAME).is_file():
            if entries or self.folder.is_dir():
                self._save_index(entries)
        return entries

    def get(self, entry_id: str) -> BankEntry:
        for entry in self.list():
            if entry.id == entry_id:
                return entry
        raise BankError(f"unknown bank entry: {entry_id}")

    def read(self, entry_id: str) -> bytes:
        """The stored bytes; refuses a file that no longer matches the hash recorded when it was stored."""
        entry = self.get(entry_id)
        try:
            data = (self.folder / entry.file).read_bytes()
        except OSError as exc:
            raise BankError(f"cannot read {entry.file}: {exc}") from exc
        if digest(data) != entry.sha256:
            raise BankError(f"{entry.file} changed since it was stored")
        return data

    # ------------------------------------------------------------------ changes

    def add(self, data: bytes, origin: int | None, now: str | None = None) -> BankEntry:
        """Store ``data`` as a new file, read it back and compare; the entry exists only if both succeed."""
        try:
            name = parse_zptc(data).name
        except ValueError as exc:
            raise BankError(f"not a patch: {exc}") from exc
        stamp = now or time.strftime("%Y%m%d-%H%M%S")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self._create(stamp, name, data)
            if path.read_bytes() != data:
                path.unlink(missing_ok=True)
                raise BankError(f"{path.name} did not read back as written")
        except OSError as exc:
            raise BankError(f"cannot store the patch in {self.folder}: {exc}") from exc
        entry = BankEntry(path.stem, path.name, name, origin, stamp, digest(data))
        entries = self.list()  # reconciles first; the new file is adopted without origin, then replaced
        entries = [e for e in entries if e.id != entry.id] + [entry]
        entries.sort(key=lambda e: (e.stored_at, e.id))
        self._save_index(entries)
        return entry

    def remove(self, entry_id: str) -> None:
        entry = self.get(entry_id)
        try:
            (self.folder / entry.file).unlink(missing_ok=True)
        except OSError as exc:
            raise BankError(f"cannot remove {entry.file}: {exc}") from exc
        self._save_index([e for e in self.list() if e.id != entry_id])

    # ------------------------------------------------------------------ internals

    def _create(self, stamp: str, name: str, data: bytes) -> Path:
        base = f"{stamp}-{safe_file_name(name)}"
        for attempt in range(1000):
            path = self.folder / (f"{base}-{attempt}.zptc" if attempt else f"{base}.zptc")
            try:
                write_exclusive(path, data)
            except FileExistsError:
                continue
            return path
        raise OSError(f"no free file name in {self.folder}")

    def _adopt(self, path: Path) -> BankEntry | None:
        try:
            data = path.read_bytes()
            name = parse_zptc(data).name
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(path.stat().st_mtime))
        except (OSError, ValueError):
            return None  # not a patch: left alone, never deleted
        return BankEntry(path.stem, path.name, name, None, stamp, digest(data))

    def _load_index(self) -> list[BankEntry]:
        try:
            raw = json.loads((self.folder / INDEX_NAME).read_text())
            return [BankEntry(**item) for item in raw["entries"]]
        except (OSError, ValueError, KeyError, TypeError):
            return []  # missing or damaged: list() adopts every file

    def _save_index(self, entries: list[BankEntry]) -> None:
        tmp = self.folder / f"{INDEX_NAME}.tmp"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"version": INDEX_VERSION, "entries": [asdict(e) for e in entries]}, indent=2) + "\n")
            os.replace(tmp, self.folder / INDEX_NAME)
        except OSError:
            pass  # the index is a convenience: the files stay and the next list() adopts them
