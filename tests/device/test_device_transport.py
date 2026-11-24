import threading

from zoomstudio.device.messages import ControlChange, ProgramChange, SysexMessage
from zoomstudio.device.transport import FakeTransport, MidoTransport, find_port_name


def test_fake_transport_scripted_replies_are_queued_per_request():
    t = FakeTransport()
    t.on(b"\x52\x00\x6e\x44", SysexMessage(b"\x01"), SysexMessage(b"\x02"))
    t.send(SysexMessage(b"\x52\x00\x6e\x44"))
    assert t.sent == [SysexMessage(b"\x52\x00\x6e\x44")]
    assert t.receive(0) == SysexMessage(b"\x01")
    assert t.receive(0) == SysexMessage(b"\x02")
    assert t.receive(0) is None


def test_fake_transport_unscripted_request_gets_no_reply_and_push_injects():
    t = FakeTransport()
    t.send(SysexMessage(b"\x99"))
    assert t.receive(0) is None
    t.push(ControlChange(control=98, value=3))
    assert t.receive(0) == ControlChange(control=98, value=3)


def test_fake_transport_receive_blocks_until_push_from_other_thread():
    t = FakeTransport()
    threading.Timer(0.05, lambda: t.push(ProgramChange(program=2))).start()
    assert t.receive(2.0) == ProgramChange(program=2)


def test_fake_transport_close_is_recorded_and_idempotent():
    t = FakeTransport()
    t.close()
    t.close()
    assert t.closed


def test_find_port_name_matches_prefix_and_skip():
    names = ["Midi Through:Midi Through Port-0 14:0", "ZOOM G Series MIDI 1", "ZOOM G Series MIDI 2"]
    assert find_port_name(names, "ZOOM G") == "ZOOM G Series MIDI 1"
    assert find_port_name(names, "ZOOM G", skip=1) == "ZOOM G Series MIDI 2"
    assert find_port_name(names, "ZOOM G", skip=2) is None
    assert find_port_name(names, "Roland") is None


def test_mido_conversion_roundtrip_without_opening_ports():
    import mido

    m = MidoTransport.to_mido(SysexMessage(b"\x52\x00\x6e\x50"))
    assert m.type == "sysex" and list(m.data) == [0x52, 0x00, 0x6E, 0x50]
    assert MidoTransport.from_mido(m) == SysexMessage(b"\x52\x00\x6e\x50")
    cc = mido.Message("control_change", channel=0, control=99, value=8)
    assert MidoTransport.from_mido(cc) == ControlChange(control=99, value=8, channel=0)
    pc = mido.Message("program_change", channel=0, program=3)
    assert MidoTransport.from_mido(pc) == ProgramChange(program=3, channel=0)
    assert MidoTransport.to_mido(ControlChange(control=32, value=4)).bytes() == [0xB0, 32, 4]
    assert MidoTransport.to_mido(ProgramChange(program=3)).bytes() == [0xC0, 3]
    assert MidoTransport.from_mido(mido.Message("clock")) is None
