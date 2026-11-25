"""Reply headers observed on a real A1 FOUR (replies do not echo the request command)."""

import pytest

from device_replies import HDR, crc_bytes, pack, patch_bytes
from jmc_guitar_zoom.device.client import PedalClient
from jmc_guitar_zoom.device.errors import PedalTimeout
from jmc_guitar_zoom.device.messages import SysexMessage
from jmc_guitar_zoom.device.transport import FakeTransport


def S(b):
    return SysexMessage(bytes(b))


PATCH_INFO = HDR + bytes([0x43, 0x32, 0x00, 0x78, 0x05, 0x32, 0x00, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00])
PATCH_DATA = patch_bytes()
READ_PATCH = HDR + bytes([0x45, 0, 0, 0, 0, 0, 0, 0x78, 0x05]) + pack(PATCH_DATA) + crc_bytes(PATCH_DATA)
CURRENT = HDR + bytes([0x64, 0x12, 0x01, 0x78, 0x05]) + pack(PATCH_DATA) + crc_bytes(PATCH_DATA)


@pytest.fixture
def t():
    return FakeTransport()


@pytest.fixture
def c(t):
    return PedalClient(t, timeout=0.2)


@pytest.mark.parametrize("req,name", [(0x52, "on"), (0x53, "off")])
def test_pc_mode_ack_is_00_00(t, c, req, name):
    t.on(HDR + bytes([req]), S(HDR + b"\x00\x00"))
    t.on(HDR + b"\x53", S(HDR + b"\x00\x00"))
    guard = c.pc_mode(name == "on")
    with guard:
        pass
    assert t.sent[0].data == HDR + bytes([req])


def test_patch_info_reply_is_cmd_43(t, c):
    t.on(HDR + b"\x44", S(PATCH_INFO))
    info = c.patch_info()
    assert (info.count, info.patch_size, info.patches_per_bank) == (50, 760, 10)


def test_read_patch_reply_is_cmd_45(t, c):
    t.on(HDR + b"\x44", S(PATCH_INFO))
    t.on(HDR + b"\x46", S(READ_PATCH))
    assert c.read_patch(1) == PATCH_DATA
    assert len(READ_PATCH) == 886


def test_current_patch_reply_is_64_12(t, c):
    t.on(HDR + b"\x64\x13", S(CURRENT))
    assert c.read_current_patch() == PATCH_DATA
    assert len(CURRENT) == 882


def test_echoed_command_is_no_longer_accepted_as_reply(t, c):
    t.on(HDR + b"\x44", S(HDR + bytes([0x44, 0x32, 0, 0x78, 5, 0x32, 0, 0x0A, 0, 0, 0])))
    with pytest.raises(PedalTimeout):
        c.patch_info()


def test_file_replies_use_60_03_status_and_60_04_data(t, c):
    wildcard = HDR + bytes([0x60, 0x04, 0x25]) + bytes(8) + b"FLST_SEQ.ZT2\x00" + bytes(10)
    status = HDR + bytes([0x60, 0x03, 0x00, 0, 0, 0, 0])
    t.on(HDR + b"\x60\x25", S(wildcard))
    t.on(HDR + b"\x60\x26", S(status))
    t.on(HDR + b"\x60\x21", S(status))
    t.on(HDR + b"\x60\x09", S(status))
    assert c.list_files() == ["FLST_SEQ.ZT2"]


def test_disk_usage_reply_is_60_04_29(t, c):
    reply = HDR + bytes.fromhex("600429010008004e3c0000000000000000000000")
    t.on(HDR + b"\x60\x29", S(reply))
    du = c.disk_usage()
    assert du.maximum == 0x4E + (0x3C << 7)
