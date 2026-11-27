"""Small per-user settings kept in the config folder: the last pedal, the audio input and the calibration."""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from jmc_guitar_zoom.calibration import CUSTOM, FENDER_STYLE, PICKUP_TYPES, PRESETS, GuitarPreset

PICKUP_POSITIONS = ("neck", "middle", "bridge")

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
ROUNDS = (3, 10)  # the rounds the assistant may take per string, inclusive
DEFAULT_ROUNDS = 5


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

    DEFAULTS = {"device": None, "channel": 0, "tolerance": 1.0, "scale_mm": 648.0, "rounds": DEFAULT_ROUNDS}

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.device: str | None = None
        self.channel = 0
        self.tolerance = 1.0
        self.scale_mm = 648.0
        self.rounds = DEFAULT_ROUNDS
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            device, channel = data.get("device"), data.get("channel")
            rounds = data.get("rounds")
            tolerance, scale = data.get("tolerance"), data.get("scale_mm")
        except (OSError, ValueError, AttributeError):
            return
        self.device = device if isinstance(device, str) and device else None
        self.channel = channel if isinstance(channel, int) and not isinstance(channel, bool) and channel >= 0 else 0
        self.tolerance = _number(tolerance, TOLERANCES, self.DEFAULTS["tolerance"])
        self.scale_mm = _number(scale, SCALES_MM, self.DEFAULTS["scale_mm"])
        ok = isinstance(rounds, int) and not isinstance(rounds, bool)
        self.rounds = max(ROUNDS[0], min(ROUNDS[1], rounds)) if ok else DEFAULT_ROUNDS

    def save(self, **changes) -> None:
        """Remember ``changes`` (device, channel, tolerance, scale_mm, rounds) and write the file."""
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


CALIBRATION_FILE_NAME = "calibration.json"
STEPS = (1, 4)  # the calibration steps: relief, action, pickups, intonation
DEFAULT_STEP = 1


def calibration_path() -> Path:
    """``<AppConfigLocation>/calibration.json``, next to the target file."""
    return default_path().with_name(CALIBRATION_FILE_NAME)


def _float(value, low: float, high: float, default: float) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return float(value) if ok and low <= value <= high else default


class CalibrationStore:
    """The calibration step, the chosen preset and the user's own values (never raises: bad data is the defaults).

    ``preset`` is the name of one of the ``PRESETS``; ``«Personalizado»`` is the user's copy, kept in ``custom``.
    Editing a value of a built-in preset moves to ``«Personalizado»`` with that preset's values plus the edit.
    ``path=None`` keeps everything in memory.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.step = DEFAULT_STEP
        self.preset = FENDER_STYLE.name
        self.custom = CUSTOM
        self._load()

    # -- reading

    def current(self) -> GuitarPreset:
        """The values in use: the built-in preset chosen or the user's own."""
        if self.preset == CUSTOM.name:
            return self.custom
        return next(p for p in PRESETS if p.name == self.preset)

    # -- changing

    def set_step(self, step: int) -> None:
        self.step = step
        self._write()

    def select_preset(self, name: str) -> None:
        """Choose a preset by name; ``«Personalizado»`` brings back the user's own values."""
        if name not in {p.name for p in PRESETS}:
            raise KeyError(name)
        self.preset = name
        self._write()

    def edit(self, **changes) -> None:
        """Change values of the preset in use (``GuitarPreset`` fields): it becomes ``«Personalizado»``."""
        self.custom = self.current().with_changes(name=CUSTOM.name, **changes)
        self.preset = CUSTOM.name
        self._write()

    # -- file

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
        except (OSError, ValueError):
            return
        step = data.get("step")
        ok = isinstance(step, int) and not isinstance(step, bool) and STEPS[0] <= step <= STEPS[1]
        self.step = step if ok else DEFAULT_STEP
        names = {p.name for p in PRESETS}
        self.preset = data["preset"] if data.get("preset") in names else FENDER_STYLE.name
        self.custom = self._load_custom(data.get("custom"))

    @staticmethod
    def _load_custom(data) -> GuitarPreset:
        if not isinstance(data, dict):
            return CUSTOM
        base = CUSTOM
        targets = []
        stored = data.get("pickup_targets") if isinstance(data.get("pickup_targets"), dict) else {}
        for target in base.pickup_targets:
            pair = stored.get(target.pickup_type)
            ok = isinstance(pair, (list, tuple)) and len(pair) == 2
            bass = _float(pair[0], 0.0, 10.0, target.bass_mm) if ok else target.bass_mm
            treble = _float(pair[1], 0.0, 10.0, target.treble_mm) if ok else target.treble_mm
            targets.append(dataclasses.replace(target, bass_mm=bass, treble_mm=treble))
        pickups = data.get("pickups")
        valid = (isinstance(pickups, list) and 0 < len(pickups) <= 3 and all(
            isinstance(x, (list, tuple)) and len(x) == 2 and x[0] in PICKUP_POSITIONS and x[1] in PICKUP_TYPES
            for x in pickups) and len({x[0] for x in pickups}) == len(pickups))
        return base.with_changes(
            relief_mm=_float(data.get("relief_mm"), 0.0, 2.0, base.relief_mm),
            action_bass_mm=_float(data.get("action_bass_mm"), 0.1, 10.0, base.action_bass_mm),
            action_treble_mm=_float(data.get("action_treble_mm"), 0.1, 10.0, base.action_treble_mm),
            radius_in=_float(data.get("radius_in"), 5.0, 30.0, base.radius_in),
            pickups=tuple((x[0], x[1]) for x in pickups) if valid else base.pickups,
            pickup_targets=tuple(targets))

    def _write(self) -> None:
        if self.path is None:
            return
        custom = self.custom
        data = {"step": self.step, "preset": self.preset,
                "custom": {"relief_mm": custom.relief_mm, "action_bass_mm": custom.action_bass_mm,
                           "action_treble_mm": custom.action_treble_mm, "radius_in": custom.radius_in,
                           "pickups": [list(x) for x in custom.pickups],
                           "pickup_targets": {t.pickup_type: [t.bass_mm, t.treble_mm]
                                              for t in custom.pickup_targets}}}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass  # not remembering the calibration is not worth interrupting it for
