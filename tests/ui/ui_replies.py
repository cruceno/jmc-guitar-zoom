"""Fake pedal replies for the UI tests (copied from tests/device/device_replies.py)."""
import binascii
from pathlib import Path

import zoomzt2

from zoomstudio.device import sysex
from zoomstudio.device.messages import SysexMessage
from zoomstudio.device.transport import FakeTransport

MODEL = 0x6E
HDR = bytes([0x52, 0x00, MODEL])
FIXTURES = Path(__file__).parent / "fixtures"

_upstream = zoomzt2.zoomzt2()


def pack(data: bytes) -> bytes:
    return bytes(_upstream.pack(data))


def crc_bytes(data: bytes) -> bytes:
    crc = binascii.crc32(data) ^ 0xFFFFFFFF
    return bytes([crc & 0x7F, (crc >> 7) & 0x7F, (crc >> 14) & 0x7F, (crc >> 21) & 0x7F, (crc >> 28) & 0x0F])


def S(data: bytes) -> SysexMessage:
    return SysexMessage(bytes(data))


def patch_reply(bank: int, loc: int, data: bytes) -> bytes:
    return (HDR + bytes([0x45, 0, 0, bank & 0x7F, bank >> 7, loc & 0x7F, loc >> 7])
            + bytes([len(data) & 0x7F, len(data) >> 7]) + pack(data) + crc_bytes(data))


def patch_info_reply(count=50, psize=760, bsize=10) -> bytes:
    return HDR + bytes([0x43, count & 0x7F, count >> 7, psize & 0x7F, psize >> 7, 0, 0,
                        bsize & 0x7F, bsize >> 7, 0, 0])


def identity_reply(model=MODEL) -> bytes:
    return bytes([0x7E, 0x00, 0x06, 0x02, 0x52, model, 0x00, 0x00, 0x00, 0x31, 0x2E, 0x30, 0x30])


def disk_reply(maximum: int, available: int) -> bytes:
    def v(n):
        return bytes([(n >> (7 * i)) & 0x7F for i in range(5)])

    return HDR + bytes([0x60, 0x04, 0x29, 0x01, 0x00, 0x08, 0x00]) + v(maximum) + v(available) + bytes([0, 0])


def fake_pedal(patches: list[bytes], disk=(3_000_000, 150_000)) -> FakeTransport:
    """A transport that answers connect + a full read of ``patches`` (locations 1..N)."""
    t = FakeTransport()
    t.on(bytes([0x7E, 0x7F, 0x06, 0x01]), S(identity_reply()))
    t.on(sysex.patch_info_request(MODEL), S(patch_info_reply(count=len(patches))))
    for loc, raw in enumerate(patches, start=1):
        bank, slot = divmod(loc - 1, 10)
        t.on(HDR + b"\x46", S(patch_reply(bank, slot, raw)))
    for _ in range(3):  # enough for a full read plus disk refreshes
        t.on(sysex.pc_mode(True, MODEL), S(HDR + b"\x00\x00"))
        t.on(sysex.pc_mode(False, MODEL), S(HDR + b"\x00\x00"))
    for _ in range(3):
        t.on(sysex.disk_usage_request(MODEL), S(disk_reply(*disk)))
    return t
