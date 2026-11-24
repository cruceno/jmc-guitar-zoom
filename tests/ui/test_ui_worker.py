from pathlib import Path

import pytest
from PySide6.QtCore import QThread

from ui_replies import FIXTURES, HDR, S, fake_pedal
from zoomstudio.device import sysex
from zoomstudio.device.messages import SysexMessage
from zoomstudio.device.transport import FakeTransport
from zoomstudio.patches.model import Patch
from zoomstudio.ui.worker import PedalWorker

HB = (FIXTURES / "53-HB-Jazz.zptc").read_bytes()
B1 = (FIXTURES / "backup" / "001.zptc").read_bytes()


def record(worker):
    events = []
    worker.connected.connect(lambda ident, info: events.append(("connected", ident.model, info.count)))
    worker.patch_loaded.connect(lambda loc, p: events.append(("patch", loc, p.name)))
    worker.disk_usage.connect(lambda du: events.append(("disk", du.maximum, du.available)))
    worker.error.connect(lambda msg: events.append(("error", msg)))
    return events


def test_connect_then_load_emits_signals_in_order(qapp):
    t = fake_pedal([B1, HB, B1])
    worker = PedalWorker(lambda: t, timeout=0.2)
    events = record(worker)
    worker.connect_pedal()
    worker.load_all_patches()
    worker.refresh_disk_usage()
    assert [e[0] for e in events] == ["connected", "patch", "patch", "patch", "disk"]
    assert events[0] == ("connected", 0x6E, 3)
    assert [e[1] for e in events[1:4]] == [1, 2, 3]
    assert events[2][2] == "HB Jazz"
    assert events[4] == ("disk", 3_000_000, 150_000)
    # one PC mode guard wraps the whole read (the disk refresh adds a second one)
    sent = [m.data for m in t.sent if isinstance(m, SysexMessage)]
    on, off = sysex.pc_mode(True, 0x6E), sysex.pc_mode(False, 0x6E)
    first_read = sent.index(HDR + b"\x46\x00\x00\x00\x00\x00\x00")
    last_read = max(i for i, d in enumerate(sent) if d.startswith(HDR + b"\x46"))
    assert sent.index(on) < first_read and sent.index(off) > last_read
    assert sent.count(on) == 2 and sent.count(off) == 2


def test_timeout_becomes_error_signal_not_exception(qapp):
    t = FakeTransport()  # never replies
    worker = PedalWorker(lambda: t, timeout=0.05)
    events = record(worker)
    worker.connect_pedal()  # must not raise
    assert events and events[0][0] == "error"
    assert "reply" in events[0][1].lower() or "timeout" in events[0][1].lower()
    worker.load_all_patches()  # not connected: also an error, not an exception
    assert [e[0] for e in events] == ["error", "error"]


def test_missing_midi_port_becomes_error(qapp):
    def factory():
        raise ConnectionError("no MIDI port found with prefix 'ZOOM G'")

    worker = PedalWorker(factory, timeout=0.05)
    events = record(worker)
    worker.connect_pedal()
    assert events == [("error", "no MIDI port found with prefix 'ZOOM G'")]


def test_disconnect_closes_transport(qapp):
    t = fake_pedal([B1])
    worker = PedalWorker(lambda: t, timeout=0.2)
    gone = []
    worker.disconnected.connect(lambda: gone.append(True))
    worker.connect_pedal()
    worker.disconnect_pedal()
    assert t.closed and gone == [True]


def test_worker_runs_in_its_own_thread(qapp, qtbot):
    t = fake_pedal([B1, HB])
    worker = PedalWorker(lambda: t, timeout=0.2)
    thread = QThread()
    worker.moveToThread(thread)
    thread.start()
    seen = []
    worker.patch_loaded.connect(lambda loc, p: seen.append((loc, QThread.currentThread())))
    try:
        with qtbot.waitSignal(worker.connected, timeout=3000):
            worker.request("connect_pedal")
        with qtbot.waitSignal(worker.loading_finished, timeout=3000):
            worker.request("load_all_patches")
    finally:
        thread.quit()
        thread.wait(3000)
    assert [loc for loc, _ in seen] == [1, 2]
    assert all(isinstance(p, QThread) for _, p in seen)
