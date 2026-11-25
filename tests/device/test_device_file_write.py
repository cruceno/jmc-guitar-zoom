"""File upload and delete, mirroring zoomzt2's file_upload / file_delete + file_close."""

import pytest

from device_replies import HDR
from zoomstudio.device import sysex
from zoomstudio.device.client import PedalClient
from zoomstudio.device.errors import PedalTimeout
from zoomstudio.device.messages import SysexMessage
from zoomstudio.device.transport import FakeTransport

STATUS = SysexMessage(HDR + bytes([0x60, 0x03, 0x00, 0, 0, 0, 0]))
NAME = b"MDL_12ST.ZD2\x00"
CLOSE = [HDR + b"\x60\x21\x40\x00\x00\x00\x00", HDR + b"\x60\x09"]


def scripted(blocks: int) -> FakeTransport:
    t = FakeTransport()
    for prefix, count in [(b"\x60\x24", 1), (b"\x60\x20", 1), (b"\x60\x05", blocks + 1),
                          (b"\x60\x23", blocks), (b"\x60\x21", 1), (b"\x60\x09", 1)]:
        for _ in range(count):
            t.on(HDR + prefix, STATUS)
    return t


def sent(t):
    return [m.data for m in t.sent if isinstance(m, SysexMessage)]


def block_payload(msg: bytes) -> bytes:
    assert msg[3:10] == b"\x60\x23\x40\x00\x00\x00\x00"
    length = msg[10] | (msg[11] << 7)
    assert msg[12:15] == bytes(3)
    data = sysex.unpack7(msg[15:-5])[:length]
    sysex.verify_crc(data, msg[-5:])
    return data


def test_write_file_sends_delete_open_blocks_and_close():
    data = bytes(range(256)) * 4 + b"tail"  # 1028 bytes: blocks of 512, 512 and 4
    t = scripted(3)
    PedalClient(t, timeout=0.2).write_file("MDL_12ST.ZD2", data)
    s = sent(t)
    assert s[0] == HDR + b"\x60\x24" + NAME
    assert s[1] == HDR + b"\x60\x20\x01" + bytes(9) + NAME
    assert s[2] == HDR + b"\x60\x05\x00"
    blocks = s[3:9:2]
    assert [len(block_payload(b)) for b in blocks] == [512, 512, 4]
    assert b"".join(block_payload(b) for b in blocks) == data
    assert s[4:10:2] == [HDR + b"\x60\x05\x00"] * 3  # every block is followed by a status request
    assert s[9:] == CLOSE


def test_write_file_of_exactly_one_block():
    t = scripted(1)
    PedalClient(t, timeout=0.2).write_file("FLST_SEQ.ZT2", b"\xff" * 512)
    s = sent(t)
    assert block_payload(s[3]) == b"\xff" * 512
    assert s[-2:] == CLOSE and len(s) == 7


def test_delete_file_sends_delete_then_close():
    t = FakeTransport()
    for prefix in (b"\x60\x24", b"\x60\x21", b"\x60\x09"):
        t.on(HDR + prefix, STATUS)
    PedalClient(t, timeout=0.2).delete_file("MDL_12ST.ZD2")
    assert sent(t) == [HDR + b"\x60\x24" + NAME] + CLOSE


@pytest.mark.parametrize("name", ["", "TOO_LONG_NAME.ZD2", "dir/X.ZD2", "ÑAME.ZD2"])
def test_bad_file_names_are_rejected_before_sending(name):
    t = FakeTransport()
    with pytest.raises(ValueError):
        PedalClient(t, timeout=0.2).write_file(name, b"x")
    with pytest.raises(ValueError):
        PedalClient(t, timeout=0.2).delete_file(name)
    assert t.sent == []


def test_empty_upload_is_rejected():
    t = FakeTransport()
    with pytest.raises(ValueError):
        PedalClient(t, timeout=0.2).write_file("X.ZD2", b"")
    assert t.sent == []


def test_write_file_without_replies_times_out():
    with pytest.raises(PedalTimeout):
        PedalClient(FakeTransport(), timeout=0.05).write_file("X.ZD2", b"abc")
