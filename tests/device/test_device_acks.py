"""PC mode and patch write are acknowledged with `00 00` (captured on a real A1 FOUR)."""

import pytest

from device_replies import HDR
from jmc_guitar_zoom.device.client import PedalClient
from jmc_guitar_zoom.device.messages import SysexMessage
from jmc_guitar_zoom.device.transport import FakeTransport

PATCH_INFO = HDR + bytes([0x43, 0x32, 0x00, 0x78, 0x05, 0x32, 0x00, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00])
ACK = SysexMessage(HDR + b"\x00\x00")
STRAY_FILE_STATUS = SysexMessage(HDR + b"\x60\x03\x01")


def test_stray_reply_is_not_taken_as_pc_mode_ack():
    t = FakeTransport()
    c = PedalClient(t, timeout=0.3)
    t.on(HDR + b"\x52", STRAY_FILE_STATUS, ACK)
    t.on(HDR + b"\x53", ACK)
    with c.pc_mode(True):
        pass
    assert t.receive(0) is None  # the real ack was consumed, not left queued


def test_stray_reply_is_not_taken_as_write_ack():
    t = FakeTransport()
    c = PedalClient(t, timeout=0.3)
    t.on(HDR + b"\x44", SysexMessage(PATCH_INFO))
    t.on(HDR + b"\x45", STRAY_FILE_STATUS, ACK)
    c.write_patch(44, bytes(760))
    assert t.receive(0) is None


def test_write_without_ack_times_out():
    from jmc_guitar_zoom.device.errors import PedalTimeout
    t = FakeTransport()
    c = PedalClient(t, timeout=0.2)
    t.on(HDR + b"\x44", SysexMessage(PATCH_INFO))
    t.on(HDR + b"\x45", STRAY_FILE_STATUS)
    with pytest.raises(PedalTimeout):
        c.write_patch(44, bytes(760))


def test_stray_reply_is_not_taken_as_editor_mode_ack():
    from jmc_guitar_zoom.device.errors import PedalTimeout
    t = FakeTransport()
    c = PedalClient(t, timeout=0.2)
    t.on(HDR + b"\x50", STRAY_FILE_STATUS)
    with pytest.raises(PedalTimeout):
        c.editor_mode(True)
