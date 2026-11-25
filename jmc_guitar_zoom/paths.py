"""Where the app keeps its data and finds Guitar Lab's cache.

From source everything stays under the repository's parent folder (``workspace_root``). A packaged (frozen)
app uses the per-user data folder of the system instead. Nothing here moves or copies existing data."""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

APP_NAME = "JMC Guitar Zoom"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def source_root() -> Path:
    """The folder that holds the jmc-guitar-zoom repo and its sibling data folders."""
    return Path(__file__).resolve().parents[1].parent


def set_app_names() -> None:
    """Set the Qt application and organisation names, so Qt's data folders are right before a QApplication exists."""
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setOrganizationName(APP_NAME)


def user_data_dir() -> Path:
    """The per-user data folder: ``~/.local/share/<app>`` on Linux, ``%APPDATA%\\<app>`` on Windows."""
    from PySide6.QtCore import QCoreApplication, QStandardPaths

    set_app_names()
    # Qt nests <organisation>/<app> and the app uses the same name for both: compute without the organisation so
    # the folder is ``<data>/JMC Guitar Zoom``, not ``<data>/JMC Guitar Zoom/JMC Guitar Zoom``.
    QCoreApplication.setOrganizationName("")
    try:
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    finally:
        QCoreApplication.setOrganizationName(APP_NAME)


def data_root() -> Path:
    """Parent of ``library/``, ``patches/`` and the rest of the stored data."""
    return user_data_dir() if is_frozen() else source_root()


def _has_zd2(folder: Path) -> bool:
    try:
        return any(p.suffix.lower() == ".zd2" for p in folder.iterdir())
    except OSError:
        return False


def _guitarlab_candidates() -> list[Path]:
    home = Path.home()
    found: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        found.append(Path(appdata) / "GL")
    pattern = "drive_c/users/*/AppData/Roaming/GL"
    for base in (home / ".wine", home / ".var/app/com.usebottles.bottles/data/bottles/bottles/*"):
        found.extend(Path(p) for p in sorted(glob.glob(str(base / pattern))))
    return found


def guitarlab_dir(root: Path | None = None) -> Path | None:
    """Guitar Lab's cache folder (read-only catalog source), or None.

    From source, ``guitarlab/GL`` next to the repository wins; then Windows ``%APPDATA%\\GL``, Wine and Bottles
    prefixes, taking the first that has ``.zd2`` files."""
    if not is_frozen():
        local = (root or source_root()) / "guitarlab" / "GL"
        if local.is_dir():
            return local
    for folder in _guitarlab_candidates():
        if folder.is_dir() and _has_zd2(folder):
            return folder
    return None
