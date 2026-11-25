"""Builders for fake pedal replies, written independently of jmc_guitar_zoom.device.sysex.

They use zoomzt2's own pack() and binascii so the tests cross-check the new code
against the upstream algorithm instead of against itself.
"""

import binascii
from pathlib import Path

import zoomzt2

MODEL = 0x6E
HDR = bytes([0x52, 0x00, MODEL])
from fixture_files import DEVICE as FIXTURES  # noqa: E402

_upstream = zoomzt2.zoomzt2()


def pack(data: bytes) -> bytes:
    return bytes(_upstream.pack(data))


def crc_bytes(data: bytes) -> bytes:
    crc = binascii.crc32(data) ^ 0xFFFFFFFF
    return bytes(
        [crc & 0x7F, (crc >> 7) & 0x7F, (crc >> 14) & 0x7F, (crc >> 21) & 0x7F, (crc >> 28) & 0x0F]
    )


def patch_bytes() -> bytes:
    return (FIXTURES / "001.zptc").read_bytes()


def patch_reply(bank: int, loc: int, data: bytes) -> bytes:
    return (
        HDR + bytes([0x45, 0, 0, bank & 0x7F, bank >> 7, loc & 0x7F, loc >> 7])
        + bytes([len(data) & 0x7F, len(data) >> 7]) + pack(data) + crc_bytes(data)
    )


def current_patch_reply(data: bytes) -> bytes:
    return HDR + bytes([0x64, 0x12, 0x01, len(data) & 0x7F, len(data) >> 7]) + pack(data) + crc_bytes(data)


def patch_info_reply(count=500, psize=760, bsize=10) -> bytes:
    return HDR + bytes(
        [0x43, count & 0x7F, count >> 7, psize & 0x7F, psize >> 7, 0, 0, bsize & 0x7F, bsize >> 7, 0, 0]
    )


def identity_reply(model=MODEL) -> bytes:
    return bytes([0x7E, 0x00, 0x06, 0x02, 0x52, model, 0x00, 0x00, 0x00, 0x31, 0x2E, 0x30, 0x30])


def ack(cmd: int = 0) -> bytes:
    """Real acknowledgement for PC mode is 00 00; other cmd values are for generic acks."""
    return HDR + (b"\x00\x00" if cmd == 0 else bytes([cmd]))


def file_name_reply(name: str) -> bytes:
    body = name.encode() + b"\x00"
    return HDR + bytes([0x60, 0x04, 0x25, 0, 0, 0, 0, 0, 0, 0, 0]) + body.ljust(13, b"\x00")


def file_end_reply() -> bytes:
    return HDR + bytes([0x60, 0x03, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])


def file_block_reply(block: bytes) -> bytes:
    return (
        HDR + bytes([0x60, 0x04, 0, 0, 0, len(block) & 0x7F, len(block) >> 7])
        + pack(block) + crc_bytes(block)
    )


def disk_reply(maximum: int, available: int) -> bytes:
    def v(n):
        return bytes([(n >> (7 * i)) & 0x7F for i in range(5)])

    return HDR + bytes([0x60, 0x04, 0x29, 0x01, 0x00, 0x08, 0x00]) + v(maximum) + v(available) + bytes([0, 0])
