"""Plain data model for a Zoom A1 FOUR patch (ZPTC version 1).

The model is lossless: everything the pedal stores that we do not understand yet
is carried in ``unknown_*`` / ``extra`` fields so that parse -> build is an identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

NAME_MAX_LEN = 10
PARAM_COUNT = 12
VOLUME_MAX = 127
MAX_EFFECT_SLOTS = 16  # sanity bound; the A1 FOUR chains seen so far hold 5-7 slots

EMPTY_SLOT_ID = 0x00000000  # marks an empty slot
WIDE_FILLER_ID = 0x00000001  # inserted by the pedal after a two-slot ("wide") effect

# param1-5 and param9-12 are 12-bit fields, param6-8 are 8-bit fields
PARAM_MAX = (4095, 4095, 4095, 4095, 4095, 255, 255, 255, 4095, 4095, 4095, 4095)


@dataclass
class EffectSlot:
    """One entry of the effect chain, including pedal placeholders."""

    effect_id: int = EMPTY_SLOT_ID
    enabled: bool = True
    params: list[int] = field(default_factory=lambda: [0] * PARAM_COUNT)
    # Bits of the EDTB record we do not understand: 3 leading bytes and a 6-bit field.
    unknown_bytes: bytes = b"\x00\x00\x00"
    unknown_bits: int = 0

    @property
    def is_empty(self) -> bool:
        return self.effect_id == EMPTY_SLOT_ID

    @property
    def is_wide_filler(self) -> bool:
        return self.effect_id == WIDE_FILLER_ID

    @property
    def is_placeholder(self) -> bool:
        """True for the empty-slot and wide-effect filler markers (not real effects)."""
        return self.is_empty or self.is_wide_filler

    def validate(self) -> None:
        if not 0 <= self.effect_id <= 0xFFFFFFFF:
            raise ValueError(f"effect_id out of range: {self.effect_id}")
        if len(self.params) != PARAM_COUNT:
            raise ValueError(f"params must hold {PARAM_COUNT} values, got {len(self.params)}")
        for n, (value, limit) in enumerate(zip(self.params, PARAM_MAX), start=1):
            if not isinstance(value, int) or not 0 <= value <= limit:
                raise ValueError(f"param{n}={value!r} outside 0..{limit}")
        if len(self.unknown_bytes) != 3:
            raise ValueError("unknown_bytes must be 3 bytes")
        if not 0 <= self.unknown_bits < 64:
            raise ValueError("unknown_bits must fit in 6 bits")


@dataclass
class Patch:
    """A whole patch as stored in a ``.zptc`` file."""

    name: str = ""
    volume: int = 100
    description: str = ""
    effects: list[EffectSlot] = field(default_factory=list)

    # Preserved raw fields (lossless round trip).
    version: int = 1
    target: int = 0x100  # bitmask of supported pedals (0x100 = A1 FOUR)
    header_data: bytes = b"\x00" * 6
    name_raw: str = ""  # on-disk 10-char name field, to keep its padding style
    desc_raw: str = ""  # description as read, to know whether it was edited
    txj1_data: bytes = b""  # Japanese (Shift-JIS) description block
    pprm: dict[str, int] = field(default_factory=dict)  # PPRM bitfields other than the volume

    def validate(self) -> None:
        if len(self.name) > NAME_MAX_LEN:
            raise ValueError(f"name longer than {NAME_MAX_LEN} characters: {self.name!r}")
        if not self.name.isascii() or any(ord(c) < 32 for c in self.name):
            raise ValueError(f"name must be printable ASCII: {self.name!r}")
        if not self.description.isascii():
            raise ValueError("description must be ASCII")
        if not isinstance(self.volume, int) or not 0 <= self.volume <= VOLUME_MAX:
            raise ValueError(f"volume outside 0..{VOLUME_MAX}: {self.volume!r}")
        if not 1 <= len(self.effects) <= MAX_EFFECT_SLOTS:
            raise ValueError(f"effect slot count outside 1..{MAX_EFFECT_SLOTS}: {len(self.effects)}")
        if len(self.header_data) != 6:
            raise ValueError("header_data must be 6 bytes")
        for slot in self.effects:
            slot.validate()
