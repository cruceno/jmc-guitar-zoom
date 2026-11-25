"""Small per-user settings kept in the config folder: today only the last pedal the editor targeted."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths

FILE_NAME = "target.json"


def default_path() -> Path:
    """``<AppConfigLocation>/target.json`` (tests redirect this function; they never touch the real one)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base or Path.home() / ".config" / "zoom-studio") / FILE_NAME


class TargetStore:
    """The last target pedal (a model id). ``path=None`` keeps it in memory; a missing or corrupt file is none."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._value: int | None = self._load()

    def _load(self) -> int | None:
        if self.path is None:
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))["target"]
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @property
    def target(self) -> int | None:
        return self._value

    def set_target(self, model_id: int) -> None:
        if model_id == self._value:
            return
        self._value = model_id
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"target": model_id}), encoding="utf-8")
        except OSError:
            pass  # not saving it is not worth interrupting the editor for
