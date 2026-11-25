"""Pure functions for the Zoom FOUR-series SysEx protocol.

Payloads are ``bytes`` without the F0/F7 framing (the mido convention), starting
with the address ``52 00 <model>``. Nothing here touches MIDI ports.

Protocol notes live in readme.md ("MIDI Operation") and in zoomzt2.py, whose
algorithms for 7-bit packing and the CRC trailer are reproduced here.
"""

from __future__ import annotations

import binascii
import os
from dataclasses import dataclass

from .errors import ChecksumError, PedalProtocolError

MANUFACTURER = 0x52
DEFAULT_MODEL = 0x6E
MAX_VALUE = (1 << 35) - 1

TUNER_NOTES = ["A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", None]
CC_TUNER_NOTE = 98
CC_TUNER_CENTS = 99

# Reply headers observed on a real A1 FOUR. Replies do NOT echo the request command:
#   PC mode 52/53 -> 00 00 | 44 -> 43 | 46 -> 45 | 64 13 -> 64 12
#   60 xx -> 60 04 <xx> for data replies, 60 03 00 for status replies.
# TODO: the replies to write 45 and editor mode 50/51 were not captured yet; they are
# assumed to be the 00 00 ack, and the client accepts any non-64 reply meanwhile.
REPLY_PATCH_INFO = b"\x43"
REPLY_READ_PATCH = b"\x45"
REPLY_CURRENT_PATCH = b"\x64\x12"
REPLY_FILE = b"\x60"


# ---------------------------------------------------------------- encoding

def packed_size(n: int) -> int:
    """Number of 7-bit bytes needed to carry n raw bytes."""
    return n + (n + 6) // 7


def pack7(data: bytes) -> bytes:
    """8-bit to 7-bit: one byte of MSBs followed by up to 7 low-bit bytes."""
    out = bytearray()
    for i in range(0, len(data), 7):
        chunk = data[i:i + 7]
        msbs = 0
        for j, byte in enumerate(chunk):
            msbs |= (byte & 0x80) >> (j + 1)
        out.append(msbs)
        out.extend(b & 0x7F for b in chunk)
    return bytes(out)


def unpack7(packet: bytes) -> bytes:
    """Inverse of :func:`pack7`; a short final group is accepted."""
    out = bytearray()
    for i in range(0, len(packet), 8):
        group = packet[i:i + 8]
        msbs = group[0]
        for j, byte in enumerate(group[1:]):
            out.append(byte | (0x80 if msbs & (0x40 >> j) else 0))
    return bytes(out)


def crc_trailer(data: bytes) -> bytes:
    """CRC32 trailer: ``crc32 ^ 0xFFFFFFFF`` as five 7-bit bytes, little endian."""
    crc = binascii.crc32(data) ^ 0xFFFFFFFF
    return bytes([(crc >> (7 * i)) & 0x7F for i in range(4)] + [(crc >> 28) & 0x0F])


def verify_crc(data: bytes, trailer: bytes) -> None:
    """Raise :class:`ChecksumError` unless the trailer matches data."""
    if len(trailer) != 5:
        raise PedalProtocolError(f"CRC trailer must be 5 bytes, got {len(trailer)}")
    value = sum(b << (7 * i) for i, b in enumerate(trailer[:4])) + ((trailer[4] & 0x0F) << 28)
    if (value ^ 0xFFFFFFFF) != binascii.crc32(data):
        raise ChecksumError(f"checksum mismatch (trailer 0x{value:08x})")


def encode_value(value: int) -> bytes:
    """Five 7-bit bytes, little endian, as used by ``64 03`` parameter messages."""
    if not 0 <= value <= MAX_VALUE:
        raise ValueError(f"value out of range: {value}")
    return bytes([(value >> (7 * i)) & 0x7F for i in range(5)])


def decode_value(raw: bytes) -> int:
    return sum((b & 0x7F) << (7 * i) for i, b in enumerate(raw[:5]))


def location_to_bank(location: int, patches_per_bank: int) -> tuple[int, int]:
    """1-based patch location to (bank, slot in bank), both 0-based."""
    if location < 1:
        raise ValueError(f"patch location is 1-based, got {location}")
    if patches_per_bank < 1:
        raise ValueError("patches_per_bank must be positive")
    return divmod(location - 1, patches_per_bank)


def header(model: int) -> bytes:
    return bytes([MANUFACTURER, 0x00, model])


def _split14(n: int) -> bytes:
    return bytes([n & 0x7F, (n >> 7) & 0x7F])


# ---------------------------------------------------------------- requests

def identity_request() -> bytes:
    return bytes([0x7E, 0x7F, 0x06, 0x01])


def editor_mode(on: bool, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + bytes([0x50 if on else 0x51])


def pc_mode(on: bool, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + bytes([0x52 if on else 0x53])


def patch_info_request(model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x44"


def read_patch_request(location: int, patches_per_bank: int, model: int = DEFAULT_MODEL) -> bytes:
    bank, loc = location_to_bank(location, patches_per_bank)
    return header(model) + b"\x46\x00\x00" + _split14(bank) + _split14(loc)


def write_patch_request(location: int, data: bytes, patches_per_bank: int,
                        model: int = DEFAULT_MODEL) -> bytes:
    if not data or len(data) > 0x3FFF:
        raise ValueError(f"patch data length must be 1..16383, got {len(data)}")
    bank, loc = location_to_bank(location, patches_per_bank)
    return (header(model) + b"\x45\x00\x00" + _split14(bank) + _split14(loc)
            + _split14(len(data)) + pack7(data) + crc_trailer(data))


def read_current_patch_request(model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x64\x13"


def set_param(slot: int, param: int, value: int, model: int = DEFAULT_MODEL) -> bytes:
    """Set one parameter of the current patch (``64 03 00 slot param value``)."""
    if not 0 <= slot <= 0x7F or not 0 <= param <= 0x7F:
        raise ValueError(f"slot/param must be 7-bit, got {slot}/{param}")
    return header(model) + bytes([0x64, 0x03, 0x00, slot, param]) + encode_value(value)


def set_patch_name_char(position: int, char: str, model: int = DEFAULT_MODEL) -> bytes:
    if not 0 <= position <= 9:
        raise ValueError(f"name position must be 0..9, got {position}")
    if len(char) != 1 or ord(char) > 0x7F:
        raise ValueError(f"name character must be one ASCII character, got {char!r}")
    return set_param(0x09, position, ord(char), model)


def set_patch_volume(value: int, model: int = DEFAULT_MODEL) -> bytes:
    return set_param(0x0A, 0x00, value, model)


def tuner(on: bool, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + bytes([0x64, 0x0B if on else 0x0C])


def _filename(name: str) -> bytes:
    return os.path.basename(name).encode("ascii") + b"\x00"


def file_check_request(name: str, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x60\x25\x00\x00" + _filename(name)


def file_list_request(first: bool, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + bytes([0x60, 0x25 if first else 0x26, 0x00, 0x00]) + _filename("*")


def file_status_request(model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x60\x05\x00"


def file_check_done_request(model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x60\x27"


def file_open_read_request(name: str, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x60\x20\x02" + bytes(9) + _filename(name)


def file_read_block_request(model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + bytes.fromhex("60 22 14 2f 60 00 0c 00 04 00 00 00".replace(" ", ""))


FILE_BLOCK_SIZE = 512  # zoomzt2's upload chunk; Guitar Lab's own size is unknown


def check_file_name(name: str) -> str:
    """Pedal file names are 8.3 ASCII with no directory, at most 12 characters."""
    if (not name or len(name) > 12 or "/" in name or "\\" in name
            or not name.isascii() or not name.isprintable()):
        raise ValueError(f"not a pedal file name: {name!r}")
    return name


def file_delete_request(name: str, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x60\x24" + _filename(check_file_name(name))


def file_open_write_request(name: str, model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x60\x20\x01" + bytes(9) + _filename(check_file_name(name))


def file_write_block_request(block: bytes, model: int = DEFAULT_MODEL) -> bytes:
    """One upload block: ``60 23 40 00 00 00 00 len(14 bit) 00 00 00`` + packed data + CRC."""
    if not 0 < len(block) <= FILE_BLOCK_SIZE:
        raise ValueError(f"block must hold 1..{FILE_BLOCK_SIZE} bytes, got {len(block)}")
    return (header(model) + b"\x60\x23\x40\x00\x00\x00\x00" + _split14(len(block)) + bytes(3)
            + pack7(block) + crc_trailer(block))


def file_close_request(model: int = DEFAULT_MODEL) -> list[bytes]:
    """The two messages that close an open file (each gets one reply)."""
    return [header(model) + b"\x60\x21\x40\x00\x00\x00\x00", header(model) + b"\x60\x09"]


def disk_usage_request(model: int = DEFAULT_MODEL) -> bytes:
    return header(model) + b"\x60\x29" + bytes(5)


# ---------------------------------------------------------------- replies

@dataclass(frozen=True)
class Identity:
    manufacturer: int
    model: int
    family: int
    member: int
    version: bytes


@dataclass(frozen=True)
class PatchInfo:
    count: int
    patch_size: int
    patches_per_bank: int


@dataclass(frozen=True)
class DiskUsage:
    maximum: int
    available: int

    @property
    def used(self) -> int:
        return self.maximum - self.available

    @property
    def used_percent(self) -> float:
        if self.maximum and self.available:
            return (1 - self.available / self.maximum) * 100
        return 0.0


def _check_7bit(payload: bytes) -> None:
    if any(b & 0x80 for b in payload):
        raise PedalProtocolError("SysEx payload contains a byte with the high bit set")


def _check_reply(payload: bytes, model: int, cmd: bytes, min_len: int) -> None:
    _check_7bit(payload)
    if payload[:3] != header(model) or payload[3:3 + len(cmd)] != cmd:
        raise PedalProtocolError(f"unexpected reply header {payload[:5].hex()}, wanted {(header(model) + cmd).hex()}")
    if len(payload) < min_len:
        raise PedalProtocolError(f"reply too short: {len(payload)} < {min_len} bytes")


def parse_identity_reply(payload: bytes) -> Identity:
    """Identity reply: 7E dev 06 02 mfr family(2) member(2) version(4).

    The model ID (0x6E on the A1 FOUR) is the low family byte.
    """
    if len(payload) < 9 or payload[0] != 0x7E or payload[2:4] != b"\x06\x02":
        raise PedalProtocolError(f"not an identity reply: {payload.hex()}")
    return Identity(
        manufacturer=payload[4],
        model=payload[5],
        family=payload[5] | (payload[6] << 7),
        member=payload[7] | (payload[8] << 7),
        version=bytes(payload[9:13]),
    )


def parse_patch_info(payload: bytes, model: int = DEFAULT_MODEL) -> PatchInfo:
    _check_reply(payload, model, REPLY_PATCH_INFO, 12)
    return PatchInfo(
        count=payload[5] * 128 + payload[4],
        patch_size=payload[7] * 128 + payload[6],
        patches_per_bank=payload[11] * 128 + payload[10],
    )


def _decode_block(payload: bytes, len_offset: int) -> bytes | None:
    """Decode ``len_lo len_hi <packed> <crc5>``; None when the length is zero."""
    length = payload[len_offset + 1] * 128 + payload[len_offset]
    if length == 0:
        return None
    start = len_offset + 2
    expected = start + packed_size(length) + 5
    if len(payload) != expected:
        raise PedalProtocolError(f"block length mismatch: declared {length} bytes, "
                                 f"message is {len(payload)} bytes, expected {expected}")
    data = unpack7(payload[start:expected - 5])
    verify_crc(data, payload[-5:])
    return data


def parse_patch_reply(payload: bytes, model: int = DEFAULT_MODEL) -> bytes:
    _check_reply(payload, model, REPLY_READ_PATCH, 12)
    data = _decode_block(payload, 10)
    if data is None:
        raise PedalProtocolError("pedal returned an empty patch")
    return data


def parse_current_patch_reply(payload: bytes, model: int = DEFAULT_MODEL) -> bytes:
    _check_reply(payload, model, REPLY_CURRENT_PATCH, 8)
    data = _decode_block(payload, 6)
    if data is None:
        raise PedalProtocolError("pedal returned an empty current patch")
    return data


def parse_disk_usage(payload: bytes, model: int = DEFAULT_MODEL) -> DiskUsage:
    _check_reply(payload, model, b"\x60", 20)
    return DiskUsage(maximum=decode_value(payload[10:15]), available=decode_value(payload[15:20]))


def parse_file_name_reply(payload: bytes, model: int = DEFAULT_MODEL) -> str | None:
    """File name from a ``60 25``/``60 26`` listing reply; None at end of listing."""
    _check_reply(payload, model, b"\x60", 5)
    if payload[4] != 4:
        return None
    raw = bytes(payload[14:27]).split(b"\x00", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PedalProtocolError("file name is not valid UTF-8") from exc


def parse_file_check_reply(payload: bytes) -> bool:
    """True when the ``60 05`` status after a file check says the file exists."""
    return bytes(payload[-5:]) == bytes(5)


def parse_file_block_reply(payload: bytes, model: int = DEFAULT_MODEL) -> bytes | None:
    """One block of file data; None when the pedal has no more data."""
    _check_reply(payload, model, b"\x60", 5)
    if payload[4] != 4 or len(payload) < 10:
        return None
    return _decode_block(payload, 8)
