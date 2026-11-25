"""One-time copy of the settings the app kept under its former name («Zoom Studio»).

The application used to be called Zoom Studio, so its config folder was ``<GenericConfigLocation>/Zoom Studio``.
Under the current name Qt looks elsewhere. ``migrate_legacy_config`` copies the three small files
(favourites, target pedal, update check time) into the new folder when the new folder lacks them and the old one
has them. It only copies: the originals are never moved, changed or deleted, and a file that already exists in the
new folder is never overwritten.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from . import favorites, settings

LEGACY_NAME = "Zoom Studio"
FILES = (favorites.FILE_NAME, settings.FILE_NAME, settings.UPDATES_FILE_NAME)


def legacy_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
    return Path(base or Path.home() / ".config") / LEGACY_NAME


def migrate_legacy_config(new_dir: Path, old_dir: Path | None = None) -> list[str]:
    """Copy the files the old folder has and the new one lacks; returns the names copied. Never raises."""
    old = Path(old_dir) if old_dir is not None else legacy_dir()
    new = Path(new_dir)
    copied: list[str] = []
    try:
        if not old.is_dir() or old.resolve() == new.resolve():
            return copied
        for name in FILES:
            source, target = old / name, new / name
            if source.is_file() and not target.exists():
                new.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append(name)
    except OSError:
        pass  # a missing migration only means the user starts with default settings
    return copied
