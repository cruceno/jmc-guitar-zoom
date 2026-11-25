"""Favourite effects: a set of effect IDs kept in a small JSON file in the user's config folder.

Favourites are a viewing aid of the editor: they never reach the pedal and are not part of any patch.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal

FILE_NAME = "favorites.json"


def default_path() -> Path:
    """``<AppConfigLocation>/favorites.json`` (tests redirect this function; they never touch the real one)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base or Path.home() / ".config" / "zoom-studio") / FILE_NAME


class FavoritesStore(QObject):
    """The favourite effect IDs. ``path=None`` keeps them in memory only. A missing or corrupt file is no favourites."""

    changed = Signal()

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self.path = Path(path) if path is not None else None
        self._ids: set[int] = self._load()

    def _load(self) -> set[int]:
        if self.path is None:
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {i for i in data["favorites"] if isinstance(i, int) and not isinstance(i, bool)}
        except (OSError, ValueError, KeyError, TypeError):
            return set()

    def ids(self) -> set[int]:
        return set(self._ids)

    def is_favorite(self, effect_id: int) -> bool:
        return effect_id in self._ids

    def set_favorite(self, effect_id: int, on: bool) -> None:
        if (effect_id in self._ids) == on:
            return
        self._ids.add(effect_id) if on else self._ids.discard(effect_id)
        self._save()
        self.changed.emit()

    def toggle(self, effect_id: int) -> bool:
        """Flip the effect and return whether it is a favourite now."""
        self.set_favorite(effect_id, effect_id not in self._ids)
        return effect_id in self._ids

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"favorites": sorted(self._ids)}), encoding="utf-8")
        except OSError:
            pass  # not saving is not worth interrupting the editor for: they stay for this session
