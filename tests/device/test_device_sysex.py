import random

import pytest

import zoomzt2
from device_replies import (
    HDR, MODEL, ack, crc_bytes, current_patch_reply, disk_reply, file_block_reply,
    file_end_reply, file_name_reply, identity_reply, pack, patch_bytes, patch_info_reply,
    patch_reply,
)
from jmc_guitar_zoom.device import sysex
from jmc_guitar_zoom.device.errors import ChecksumError, PedalProtocolError


def test_pack_matches_upstream_and_roundtrips():
    up = zoomzt2.zoomzt2()
    rng = random.Random(1)
    for n in [0, 1, 6, 7, 8, 14, 15, 760]:
        raw = bytes(rng.randrange(256) for _ in range(n))
        assert sysex.pack7(raw) == bytes(up.pack(raw))
        assert sysex.unpack7(sysex.pack7(raw)) == raw
        assert len(sysex.pack7(raw)) == sysex.packed_size(n)
    assert sysex.unpack7(sysex.pack7(patch_bytes())) == patch_bytes()


def test_crc_trailer_matches_upstream_and_detects_corruption():
    data = patch_bytes()
    trailer = sysex.crc_trailer(data)
    assert trailer == crc_bytes(data) and len(trailer) == 5
    sysex.verify_crc(data, trailer)
    with pytest.raises(ChecksumError):
        sysex.verify_crc(bytes([data[0] ^ 1]) + data[1:], trailer)


def test_value_encoding_7bit_little_endian():
    assert sysex.encode_value(0x01000010) == bytes([0x10, 0, 0, 0x08, 0])
    assert sysex.encode_value(117) == bytes([0x75, 0, 0, 0, 0])
    assert sysex.decode_value(bytes([0x10, 0, 0, 0x08, 0])) == 0x01000010
    for bad in (-1, 1 << 35):
        with pytest.raises(ValueError):
            sysex.encode_value(bad)


def test_location_to_bank():
    assert sysex.location_to_bank(1, 10) == (0, 0)
    assert sysex.location_to_bank(44, 10) == (4, 3)
    assert sysex.location_to_bank(1301, 10) == (130, 0)
    for bad in (0, -3):
        with pytest.raises(ValueError):
            sysex.location_to_bank(bad, 10)


def test_simple_builders_bytes():
    assert sysex.identity_request() == bytes([0x7E, 0x7F, 0x06, 0x01])
    assert sysex.editor_mode(True, MODEL) == HDR + b"\x50"
    assert sysex.editor_mode(False, MODEL) == HDR + b"\x51"
    assert sysex.pc_mode(True, MODEL) == HDR + b"\x52"
    assert sysex.pc_mode(False, MODEL) == HDR + b"\x53"
    assert sysex.patch_info_request(MODEL) == HDR + b"\x44"
    assert sysex.read_current_patch_request(MODEL) == HDR + b"\x64\x13"
    assert sysex.tuner(True, MODEL) == HDR + b"\x64\x0b"
    assert sysex.tuner(False, MODEL) == HDR + b"\x64\x0c"


def test_read_patch_request_maps_location_to_bank():
    assert sysex.read_patch_request(44, 10, MODEL) == HDR + bytes([0x46, 0, 0, 4, 0, 3, 0])
    assert sysex.read_patch_request(1301, 10, MODEL) == HDR + bytes([0x46, 0, 0, 2, 1, 0, 0])


def test_write_patch_request_layout():
    data = patch_bytes()
    msg = sysex.write_patch_request(44, data, 10, MODEL)
    assert msg == HDR + bytes([0x45, 0, 0, 4, 0, 3, 0, 0x78, 5]) + pack(data) + crc_bytes(data)
    assert all(b < 0x80 for b in msg)
    with pytest.raises(ValueError):
        sysex.write_patch_request(44, b"", 10, MODEL)


def test_set_param_and_friends():
    assert sysex.set_param(0, 1, 0x01000010, MODEL) == HDR + bytes([0x64, 0x03, 0, 0, 1, 0x10, 0, 0, 8, 0])
    assert sysex.set_patch_name_char(2, "a", MODEL) == HDR + bytes([0x64, 0x03, 0, 9, 2, 0x61, 0, 0, 0, 0])
    assert sysex.set_patch_volume(0x3D, MODEL) == HDR + bytes([0x64, 0x03, 0, 0x0A, 0, 0x3D, 0, 0, 0, 0])
    for bad in ((128, 1), (-1, 1), (0, 128)):
        with pytest.raises(ValueError):
            sysex.set_param(bad[0], bad[1], 0, MODEL)
    with pytest.raises(ValueError):
        sysex.set_patch_name_char(10, "a", MODEL)
    with pytest.raises(ValueError):
        sysex.set_patch_name_char(0, "é", MODEL)


def test_file_request_builders():
    assert sysex.file_check_request("FLST_SEQ.ZT2", MODEL) == HDR + b"\x60\x25\x00\x00FLST_SEQ.ZT2\x00"
    assert sysex.file_check_request("dir/A.ZD2", MODEL) == HDR + b"\x60\x25\x00\x00A.ZD2\x00"
    assert sysex.file_list_request(True, MODEL) == HDR + b"\x60\x25\x00\x00*\x00"
    assert sysex.file_list_request(False, MODEL) == HDR + b"\x60\x26\x00\x00*\x00"
    assert sysex.file_status_request(MODEL) == HDR + b"\x60\x05\x00"
    assert sysex.file_check_done_request(MODEL) == HDR + b"\x60\x27"
    assert sysex.file_open_read_request("A.ZD2", MODEL) == HDR + b"\x60\x20\x02" + bytes(9) + b"A.ZD2\x00"
    assert sysex.file_read_block_request(MODEL) == HDR + bytes.fromhex("60 22 14 2f 60 00 0c 00 04 00 00 00".replace(" ", ""))
    assert sysex.file_close_request(MODEL) == [HDR + bytes.fromhex("6021400000" "0000"), HDR + b"\x60\x09"]
    assert sysex.disk_usage_request(MODEL) == HDR + b"\x60\x29" + bytes(5)


def test_parse_identity():
    ident = sysex.parse_identity_reply(identity_reply(0x6E))
    assert (ident.manufacturer, ident.model) == (0x52, 0x6E)
    assert ident.version == b"1.00"
    with pytest.raises(PedalProtocolError):
        sysex.parse_identity_reply(bytes([0x7E, 0, 6, 2]))
    with pytest.raises(PedalProtocolError):
        sysex.parse_identity_reply(bytes([0x7E, 0, 6, 3, 0x52, 0x6E, 0, 0, 0]))


def test_parse_patch_info():
    info = sysex.parse_patch_info(patch_info_reply(count=500, psize=760, bsize=10), MODEL)
    assert (info.count, info.patch_size, info.patches_per_bank) == (500, 760, 10)
    with pytest.raises(PedalProtocolError):
        sysex.parse_patch_info(ack(0x44), MODEL)
    with pytest.raises(PedalProtocolError):
        sysex.parse_patch_info(patch_info_reply()[:5] + bytes([0x45]) , MODEL)


def test_parse_patch_reply_roundtrip_and_errors():
    data = patch_bytes()
    assert sysex.parse_patch_reply(patch_reply(4, 3, data), MODEL) == data
    bad_crc = bytearray(patch_reply(4, 3, data))
    bad_crc[-1] ^= 0x01
    with pytest.raises(ChecksumError):
        sysex.parse_patch_reply(bytes(bad_crc), MODEL)
    corrupted = bytearray(patch_reply(4, 3, data))
    corrupted[40] ^= 0x01
    with pytest.raises(ChecksumError):
        sysex.parse_patch_reply(bytes(corrupted), MODEL)
    with pytest.raises(PedalProtocolError):
        sysex.parse_patch_reply(patch_reply(4, 3, data)[:-3], MODEL)
    with pytest.raises(PedalProtocolError):
        sysex.parse_patch_reply(patch_reply(4, 3, b""), MODEL)
    with pytest.raises(PedalProtocolError):
        sysex.parse_patch_reply(ack(0x46), MODEL)


def test_parse_current_patch():
    data = patch_bytes()
    assert sysex.parse_current_patch_reply(current_patch_reply(data), MODEL) == data
    bad = bytearray(current_patch_reply(data))
    bad[20] ^= 0x02
    with pytest.raises(ChecksumError):
        sysex.parse_current_patch_reply(bytes(bad), MODEL)


def test_parse_disk_usage():
    du = sysex.parse_disk_usage(disk_reply(1_000_000, 250_000), MODEL)
    assert (du.maximum, du.available) == (1_000_000, 250_000)
    assert du.used == 750_000
    assert du.used_percent == pytest.approx(75.0)
    assert sysex.parse_disk_usage(disk_reply(0, 0), MODEL).used_percent == 0
    with pytest.raises(PedalProtocolError):
        sysex.parse_disk_usage(HDR + b"\x60\x04\x29", MODEL)


def test_parse_file_listing_and_blocks():
    assert sysex.parse_file_name_reply(file_name_reply("FLST_SEQ.ZT2"), MODEL) == "FLST_SEQ.ZT2"
    assert sysex.parse_file_name_reply(file_end_reply(), MODEL) is None
    block = bytes(range(200))
    assert sysex.parse_file_block_reply(file_block_reply(block), MODEL) == block
    assert sysex.parse_file_block_reply(file_end_reply(), MODEL) is None
    bad = bytearray(file_block_reply(block))
    bad[-2] ^= 0x04
    with pytest.raises(ChecksumError):
        sysex.parse_file_block_reply(bytes(bad), MODEL)
    assert sysex.parse_file_check_reply(HDR + b"\x60\x05" + bytes(8) + bytes(5)) is True
    assert sysex.parse_file_check_reply(HDR + b"\x60\x05" + bytes(8) + bytes([0, 0, 1, 0, 0])) is False


def test_non_7bit_payload_is_rejected():
    msg = bytearray(patch_reply(4, 3, patch_bytes()))
    msg[30] = 0x90
    with pytest.raises(PedalProtocolError):
        sysex.parse_patch_reply(bytes(msg), MODEL)
