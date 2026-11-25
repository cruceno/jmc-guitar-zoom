"""Timestamped backups of a patch buffer read from the pedal (never overwritten)."""
from __future__ import annotations

import time
from pathlib import Path


def write_backup(directory: Path, location: int, data: bytes, now: str | None = None) -> Path:
    """Store ``data`` as ``<directory>/NNN-<timestamp>[-k].zptc`` and return the path.

    The file is created exclusively: an existing file is never touched, a numeric
    suffix is added instead.
    """
    return _write_exclusive(directory, f"{location:03d}", ".zptc", data, now)


def write_file_backup(directory: Path, name: str, data: bytes, now: str | None = None) -> Path:
    """Store a pedal file as ``<directory>/<timestamp>[-k]-<name>``, never overwriting."""
    return _write_exclusive(directory, None, f"-{name}", data, now)


def _write_exclusive(directory: Path, prefix: str | None, tail: str, data: bytes, now: str | None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    for attempt in range(1000):
        suffix = f"-{attempt}" if attempt else ""
        head = f"{prefix}-{stamp}{suffix}" if prefix else f"{stamp}{suffix}"
        path = directory / f"{head}{tail}"
        try:
            with open(path, "xb") as handle:
                handle.write(data)
        except FileExistsError:
            continue
        return path
    raise OSError(f"could not find a free backup name in {directory}")
