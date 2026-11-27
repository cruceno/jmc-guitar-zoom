"""Guitar presets for the calibration assistant: typical starting values, editable by the user.

The numbers are common starting points taken from luthier practice, not factory specifications of any
brand: the presets are named after a style («Estilo Fender (simple)», «Estilo Gibson (humbucker)») and the
user is expected to edit them (see ``GuitarPreset.with_changes`` and the «Personalizado» copy).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

SINGLE_COIL = "single_coil"
HUMBUCKER = "humbucker"
P90 = "p90"
PICKUP_TYPES = (SINGLE_COIL, HUMBUCKER, P90)

BRIDGE_SADDLES = "saddles"  # each saddle has its own height screw (Fender style)
BRIDGE_TWO_POSTS = "two_posts"  # height only at two posts, bass and treble (Tune-o-matic, Ibanez Gibraltar)
BRIDGE_TYPES = (BRIDGE_SADDLES, BRIDGE_TWO_POSTS)
DEFAULT_POST_SPACING_MM = 74.0


@dataclass(frozen=True)
class PickupTarget:
    """Pickup height for one type, in mm: pole top to the string underside, string fretted at the last fret.

    ``bass_mm`` is measured under string ``bass_string`` (6), ``treble_mm`` under ``treble_string`` (1).
    """

    pickup_type: str
    bass_mm: float
    treble_mm: float
    bass_string: int = 6
    treble_string: int = 1


@dataclass(frozen=True)
class GuitarPreset:
    """Starting values for one guitar. Distances are in mm, the fretboard radius in inches.

    ``action_bass_mm`` and ``action_treble_mm`` are the action at the 12th fret of strings 6 and 1;
    ``bridge_span_mm`` is the E-to-E string spacing at the bridge; ``pickups`` maps each selector position
    (``"neck"``, ``"middle"``, ``"bridge"``) to a pickup type, in order. ``bridge_type`` says where the action
    height is set: at every saddle or at two posts (then ``post_spacing_mm`` is the post-to-post distance).
    """

    name: str
    relief_mm: float
    action_bass_mm: float
    action_treble_mm: float
    radius_in: float
    bridge_span_mm: float = 52.0
    pickups: tuple[tuple[str, str], ...] = ()
    pickup_targets: tuple[PickupTarget, ...] = ()
    bridge_type: str = BRIDGE_SADDLES
    post_spacing_mm: float = DEFAULT_POST_SPACING_MM  # centre to centre, only used for two posts

    def with_changes(self, **changes) -> GuitarPreset:
        """A copy with some fields replaced; this preset is left alone."""
        return dataclasses.replace(self, **changes)

    def pickup_type(self, position: str) -> str:
        for name, kind in self.pickups:
            if name == position:
                return kind
        raise ValueError(f"this guitar has no pickup in the {position!r} position")

    def target_for_type(self, pickup_type: str) -> PickupTarget:
        for target in self.pickup_targets:
            if target.pickup_type == pickup_type:
                return target
        raise ValueError(f"no height target for the pickup type {pickup_type!r}")

    def target_for(self, position: str) -> PickupTarget:
        return self.target_for_type(self.pickup_type(position))


DEFAULT_PICKUP_TARGETS = (
    PickupTarget(SINGLE_COIL, 3.2, 2.4),
    PickupTarget(HUMBUCKER, 2.4, 1.6),
    PickupTarget(P90, 3.2, 2.4),
)

FENDER_STYLE = GuitarPreset(
    "Estilo Fender (simple)", relief_mm=0.25, action_bass_mm=1.8, action_treble_mm=1.6, radius_in=9.5,
    pickups=(("neck", SINGLE_COIL), ("middle", SINGLE_COIL), ("bridge", SINGLE_COIL)),
    pickup_targets=DEFAULT_PICKUP_TARGETS)

GIBSON_STYLE = GuitarPreset(
    "Estilo Gibson (humbucker)", relief_mm=0.30, action_bass_mm=2.0, action_treble_mm=1.5, radius_in=12,
    pickups=(("neck", HUMBUCKER), ("bridge", HUMBUCKER)), pickup_targets=DEFAULT_PICKUP_TARGETS,
    bridge_type=BRIDGE_TWO_POSTS)

CUSTOM = FENDER_STYLE.with_changes(name="Personalizado")

PRESETS = (FENDER_STYLE, GIBSON_STYLE, CUSTOM)
