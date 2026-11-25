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


UPDATES_FILE_NAME = "updates.json"
DAY_SECONDS = 24 * 60 * 60


def update_path() -> Path:
    """``<AppConfigLocation>/updates.json``, next to the target file (so tests that redirect one redirect both)."""
    return default_path().with_name(UPDATES_FILE_NAME)


class UpdateStore:
    """When the effect channel was last checked, so the start-up check runs at most once a day.

    ``path=None`` keeps it in memory; a missing or corrupt file means never checked.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.last_check: float | None = self._load()

    def _load(self) -> float | None:
        if self.path is None:
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))["last_check"]
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def due(self, now: float) -> bool:
        """True when it was never checked, a day has passed, or the clock went back past the last check."""
        return self.last_check is None or now < self.last_check or now - self.last_check >= DAY_SECONDS

    def mark_checked(self, now: float) -> None:
        self.last_check = now
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"last_check": now}), encoding="utf-8")
        except OSError:
            pass  # a daily check that cannot be remembered runs again next time: harmless
