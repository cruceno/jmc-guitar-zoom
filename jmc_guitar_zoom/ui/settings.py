"""Small per-user settings kept in the config folder: today only the last pedal the editor targeted."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths

FILE_NAME = "target.json"


def default_path() -> Path:
    """``<AppConfigLocation>/target.json`` (tests redirect this function; they never touch the real one)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base or Path.home() / ".config" / "jmc-guitar-zoom") / FILE_NAME


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


INTONATION_FILE_NAME = "intonation.json"
TOLERANCES = (0.5, 1.0, 2.0)  # cents
SCALES_MM = (628.0, 635.0, 648.0, 650.0)
REFERENCES = ("open", "harmonic")


def intonation_path() -> Path:
    """``<AppConfigLocation>/intonation.json``, next to the target file."""
    return default_path().with_name(INTONATION_FILE_NAME)


def _number(value, allowed: tuple[float, ...], default: float) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) in allowed
    return float(value) if ok else default


class IntonationStore:
    """The audio input and the assistant's options of the last session (never raises: bad data is the defaults).

    ``path=None`` keeps them in memory. A stored device that is no longer listed is the screen's business.
    """

    DEFAULTS = {"device": None, "channel": 0, "tolerance": 1.0, "scale_mm": 648.0, "reference": "open"}

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.device: str | None = None
        self.channel = 0
        self.tolerance = 1.0
        self.scale_mm = 648.0
        self.reference = "open"
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            device, channel = data.get("device"), data.get("channel")
            reference = data.get("reference")
            tolerance, scale = data.get("tolerance"), data.get("scale_mm")
        except (OSError, ValueError, AttributeError):
            return
        self.device = device if isinstance(device, str) and device else None
        self.channel = channel if isinstance(channel, int) and not isinstance(channel, bool) and channel >= 0 else 0
        self.tolerance = _number(tolerance, TOLERANCES, self.DEFAULTS["tolerance"])
        self.scale_mm = _number(scale, SCALES_MM, self.DEFAULTS["scale_mm"])
        self.reference = reference if reference in REFERENCES else "open"

    def save(self, **changes) -> None:
        """Remember ``changes`` (device, channel, tolerance, scale_mm, reference) and write the file."""
        for key, value in changes.items():
            if key not in self.DEFAULTS:
                raise KeyError(key)
            setattr(self, key, value)
        if self.path is None:
            return
        data = {key: getattr(self, key) for key in self.DEFAULTS}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass  # not remembering the input is not worth interrupting the assistant for
