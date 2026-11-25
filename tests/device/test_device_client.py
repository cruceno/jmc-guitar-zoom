import pytest

from device_replies import (
    HDR, MODEL, ack, current_patch_reply, disk_reply, file_block_reply, file_end_reply,
    file_name_reply, identity_reply, pack, patch_bytes, patch_info_reply, patch_reply,
)
from zoomstudio.device import sysex
from zoomstudio.device.client import PedalClient
from zoomstudio.device.errors import (
    ChecksumError, PedalError, PedalFileNotFound, PedalProtocolError, PedalTimeout,
)
from zoomstudio.device.messages import ControlChange, ProgramChange, SysexMessage, TunerReading
from zoomstudio.device.transport import FakeTransport


def S(b):
    return SysexMessage(bytes(b))


@pytest.fixture
def t():
    return FakeTransport()


@pytest.fixture
def client(t):
    return PedalClient(t, timeout=0.2)


def script(t, prefix, *replies):
    """One reply per send, in order."""
    for r in replies:
        t.on(prefix, r)


def sent_data(t):
    return [m.data for m in t.sent if isinstance(m, SysexMessage)]


def test_identify_sets_model_and_uses_it_afterwards(t, client):
    t.on(bytes([0x7E, 0x7F, 0x06, 0x01]), S(identity_reply(0x71)))
    ident = client.identify()
    assert ident.model == 0x71 and client.model_id == 0x71
    t.on(bytes([0x52, 0x00, 0x71, 0x44]), S(bytes([0x52, 0, 0x71, 0x43, 1, 0, 0, 6, 0, 0, 10, 0])))
    assert client.patch_info().patches_per_bank == 10
    assert sent_data(t)[-1] == bytes([0x52, 0, 0x71, 0x44])


def test_patch_info_is_typed_and_cached_for_location_math(t, client):
    t.on(HDR + b"\x44", S(patch_info_reply(count=500, psize=760, bsize=10)))
    info = client.patch_info()
    assert (info.count, info.patch_size, info.patches_per_bank) == (500, 760, 10)
    t.on(HDR + b"\x46", S(patch_reply(4, 3, patch_bytes())))
    assert client.read_patch(44) == patch_bytes()
    # only one 44 request: bank size came from the cache
    assert sent_data(t).count(HDR + b"\x44") == 1
    assert sent_data(t)[-1] == HDR + bytes([0x46, 0, 0, 4, 0, 3, 0])


def test_read_patch_fetches_patch_info_when_unknown(t, client):
    t.on(HDR + b"\x44", S(patch_info_reply()))
    t.on(HDR + b"\x46", S(patch_reply(0, 0, patch_bytes())))
    assert client.read_patch(1) == patch_bytes()
    assert sent_data(t) == [HDR + b"\x44", HDR + bytes([0x46, 0, 0, 0, 0, 0, 0])]


def test_read_patch_checksum_error_never_returns_data(t, client):
    t.on(HDR + b"\x44", S(patch_info_reply()))
    bad = bytearray(patch_reply(0, 0, patch_bytes()))
    bad[-1] ^= 1
    t.on(HDR + b"\x46", S(bad))
    with pytest.raises(ChecksumError):
        client.read_patch(1)


def test_timeout_raises_typed_error_after_the_configured_time(t, client):
    t.on(HDR + b"\x44", S(patch_info_reply()))
    client.patch_info()
    with pytest.raises(PedalTimeout):
        client.read_patch(1)  # no scripted reply
    assert issubclass(PedalTimeout, PedalError) and issubclass(ChecksumError, PedalProtocolError)


def test_per_request_timeout_override(t):
    c = PedalClient(t, timeout=30)
    import time

    start = time.monotonic()
    with pytest.raises(PedalTimeout):
        c.patch_info(timeout=0.05)
    assert time.monotonic() - start < 2


def test_unsolicited_messages_are_not_mistaken_for_replies(t, client):
    events = []
    client.subscribe(events.append)
    noise = [
        ControlChange(control=98, value=2),
        S(HDR + bytes([0x64, 0x0B])),
        S(HDR + bytes([0x64, 0x03, 0x00, 0x0A, 0x0C, 0x06, 0, 0, 0, 0])),
        S(HDR + b"\x46\x00\x00"),  # a different reply header than the one awaited
    ]
    t.on(HDR + b"\x44", *noise, S(patch_info_reply()))
    info = client.patch_info()
    assert info.count == 500
    assert events[0] == TunerReading(note="B", offset=0)
    assert S(HDR + bytes([0x64, 0x0B])) in events
    assert S(HDR + b"\x46\x00\x00") in events


def test_stale_messages_before_a_request_go_to_subscribers(t, client):
    events = []
    client.subscribe(events.append)
    t.push(S(HDR + b"\x44" + bytes([9, 9, 9, 9, 9, 9, 9, 9])))  # late reply of an older request
    t.on(HDR + b"\x44", S(patch_info_reply()))
    assert client.patch_info().count == 500
    assert len(events) == 1


def test_unsubscribe(t, client):
    events = []
    unsub = client.subscribe(events.append)
    unsub()
    t.push(ControlChange(control=98, value=1))
    client.poll()
    assert events == []


def test_write_patch_sends_exact_message_and_waits_for_ack(t, client):
    t.on(HDR + b"\x44", S(patch_info_reply()))
    t.on(HDR + b"\x45", S(ack()))
    client.write_patch(44, patch_bytes())
    assert sent_data(t)[-1] == sysex.write_patch_request(44, patch_bytes(), 10, MODEL)
    assert sent_data(t)[-1][:10] == HDR + bytes([0x45, 0, 0, 4, 0, 3, 0])


def test_write_patch_times_out_without_ack(t, client):
    t.on(HDR + b"\x44", S(patch_info_reply()))
    with pytest.raises(PedalTimeout):
        client.write_patch(44, patch_bytes())


def test_read_current_patch(t, client):
    t.on(HDR + b"\x64\x13", S(current_patch_reply(patch_bytes())))
    assert client.read_current_patch() == patch_bytes()
    assert sent_data(t) == [HDR + b"\x64\x13"]


def test_set_param_sends_without_waiting(t, client):
    client.set_param(0, 1, 0x01000010)
    assert sent_data(t) == [HDR + bytes([0x64, 3, 0, 0, 1, 0x10, 0, 0, 8, 0])]
    with pytest.raises(ValueError):
        client.set_param(0, 200, 1)
    assert len(t.sent) == 1


def test_patch_name_char_and_volume(t, client):
    client.set_patch_name_char(0, "H")
    client.set_patch_volume(60)
    assert sent_data(t) == [
        HDR + bytes([0x64, 3, 0, 9, 0, 0x48, 0, 0, 0, 0]),
        HDR + bytes([0x64, 3, 0, 0x0A, 0, 60, 0, 0, 0, 0]),
    ]


def test_select_patch_sends_cc0_cc32_pc(t, client):
    t.on(HDR + b"\x44", S(patch_info_reply()))
    client.select_patch(44)
    assert t.sent[1:] == [ControlChange(0, 0), ControlChange(32, 4), ProgramChange(3)]


def test_modes_send_expected_bytes_and_wait_for_ack(t, client):
    t.on(HDR + b"\x50", S(ack()))
    t.on(HDR + b"\x51", S(ack()))
    client.editor_mode(True)
    client.editor_mode(False)
    assert sent_data(t) == [HDR + b"\x50", HDR + b"\x51"]


def test_editor_mode_not_acked_by_editor_notifications(t, client):
    t.on(HDR + b"\x50", S(HDR + bytes([0x64, 0x0B])))
    with pytest.raises(PedalTimeout):
        client.editor_mode(True)


def test_pc_mode_context_manager_always_turns_it_off(t, client):
    t.on(HDR + b"\x52", S(ack()))
    t.on(HDR + b"\x53", S(ack()))
    with pytest.raises(RuntimeError):
        with client.pc_mode(True):
            raise RuntimeError("boom")
    assert sent_data(t) == [HDR + b"\x52", HDR + b"\x53"]


def test_pc_mode_exit_failure_does_not_mask_original_error(t, client):
    t.on(HDR + b"\x52", S(ack()))  # no reply for 53
    with pytest.raises(RuntimeError):
        with client.pc_mode(True):
            raise RuntimeError("boom")


def test_pc_mode_off_failure_surfaces_when_body_succeeded(t, client):
    t.on(HDR + b"\x52", S(ack()))
    with pytest.raises(PedalTimeout):
        with client.pc_mode(True):
            pass


def test_tuner_on_off_and_cc_parsing(t, client):
    events = []
    client.subscribe(events.append)
    client.tuner(True)
    client.tuner(False)
    assert sent_data(t) == [HDR + b"\x64\x0b", HDR + b"\x64\x0c"]
    t.push(ControlChange(control=98, value=3))   # C
    t.push(ControlChange(control=99, value=10))  # +2
    t.push(ControlChange(control=98, value=12))  # no note
    t.push(ControlChange(control=7, value=1))    # unrelated CC passes through raw
    assert client.poll() == 4
    assert events == [
        TunerReading(note="C", offset=0),
        TunerReading(note="C", offset=2),
        TunerReading(note=None, offset=2),
        ControlChange(control=7, value=1),
    ]


def test_list_files_loop_and_close(t, client):
    t.on(HDR + b"\x60\x25", S(file_name_reply("FLST_SEQ.ZT2")))
    script(t, HDR + b"\x60\x26", S(file_name_reply("A.ZD2")), S(file_end_reply()))
    t.on(HDR + b"\x60\x21", S(ack(0x60)))
    t.on(HDR + b"\x60\x09", S(ack(0x60)))
    assert client.list_files() == ["FLST_SEQ.ZT2", "A.ZD2"]
    seq = sent_data(t)
    assert seq[0] == sysex.file_list_request(True, MODEL)
    assert seq[1:3] == [sysex.file_list_request(False, MODEL)] * 2
    assert seq[3:] == sysex.file_close_request(MODEL)


def test_read_file_full_sequence(t, client):
    block1, block2 = bytes(range(256)) * 2, b"tail"
    ok = S(HDR + b"\x60\x03\x00" + bytes(5) + bytes(5))
    t.on(HDR + b"\x60\x25", S(ack(0x60)))
    script(t, HDR + b"\x60\x05", ok, S(ack(0x60)), S(file_block_reply(block1)),
           S(ack(0x60)), S(file_block_reply(block2)), S(ack(0x60)), S(file_end_reply()))
    t.on(HDR + b"\x60\x27", S(ack(0x60)))
    script(t, HDR + b"\x60\x20", S(ack(0x60)), S(ack(0x60)))
    script(t, HDR + b"\x60\x22", S(ack(0x60)), S(ack(0x60)), S(ack(0x60)))
    t.on(HDR + b"\x60\x21", S(ack(0x60)))
    t.on(HDR + b"\x60\x09", S(ack(0x60)))
    assert client.read_file("A.ZD2") == block1 + block2
    seq = sent_data(t)
    assert seq[0] == sysex.file_check_request("A.ZD2", MODEL)
    assert seq[-2:] == sysex.file_close_request(MODEL)
    assert all(m[3] == 0x60 for m in seq)
    assert not any(m[4] in (0x23, 0x24) for m in seq)  # never uploads or deletes


def test_read_file_not_found(t, client):
    t.on(HDR + b"\x60\x25", S(ack(0x60)))
    t.on(HDR + b"\x60\x05", S(HDR + b"\x60\x03\x00" + bytes(5) + bytes([0, 0, 0, 0, 1])))
    t.on(HDR + b"\x60\x27", S(ack(0x60)))
    with pytest.raises(PedalFileNotFound):
        client.read_file("NOPE.ZD2")


def test_read_file_checksum_error_still_closes_file(t, client):
    bad = bytearray(file_block_reply(b"hello world"))
    bad[-1] ^= 1
    t.on(HDR + b"\x60\x25", S(ack(0x60)))
    script(t, HDR + b"\x60\x05", S(HDR + b"\x60\x03\x00" + bytes(10)), S(ack(0x60)), S(bytes(bad)))
    t.on(HDR + b"\x60\x27", S(ack(0x60)))
    script(t, HDR + b"\x60\x20", S(ack(0x60)), S(ack(0x60)))
    t.on(HDR + b"\x60\x22", S(ack(0x60)))
    t.on(HDR + b"\x60\x21", S(ack(0x60)))
    t.on(HDR + b"\x60\x09", S(ack(0x60)))
    with pytest.raises(ChecksumError):
        client.read_file("A.ZD2")
    assert sent_data(t)[-2:] == sysex.file_close_request(MODEL)


def test_disk_usage(t, client):
    t.on(HDR + b"\x60\x29", S(disk_reply(2_000_000, 500_000)))
    du = client.disk_usage()
    assert (du.maximum, du.available) == (2_000_000, 500_000)
    assert du.used_percent == pytest.approx(75.0)
    assert sent_data(t) == [sysex.disk_usage_request(MODEL)]
