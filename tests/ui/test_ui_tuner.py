import pytest

from ui_replies import FIXTURES, fake_pedal, patch_reply
from jmc_guitar_zoom.device import sysex
from jmc_guitar_zoom.device.messages import ControlChange, SysexMessage
from jmc_guitar_zoom.effects.catalog import load_catalog
from jmc_guitar_zoom.ui.main_window import MainWindow
from jmc_guitar_zoom.ui.worker import PedalWorker

BACKUP = FIXTURES / "backup"
HB = (FIXTURES / "53-HB-Jazz.zptc").read_bytes()
ON, OFF = sysex.tuner(True, 0x6E), sysex.tuner(False, 0x6E)
HDR = sysex.header(0x6E)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"))


@pytest.fixture
def pedal(qtbot, catalog):
    transport = fake_pedal([(BACKUP / "001.zptc").read_bytes(), HB])
    for _ in range(10):  # editor mode 50/51 is acknowledged with 00 00 (captured on hardware)
        transport.on(HDR + b"\x50", SysexMessage(HDR + b"\x00\x00"))
        transport.on(HDR + b"\x51", SysexMessage(HDR + b"\x00\x00"))
    w = MainWindow(catalog, a1_ids=None, transport_factory=lambda: transport)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.patches_loaded, timeout=5000):
        w.connect_button.click()
    return w, transport


def sent_sysex(transport):
    return [m.data for m in transport.sent if isinstance(m, SysexMessage)]


def reading(transport, note, cents):
    transport.push(ControlChange(98, note))
    transport.push(ControlChange(99, cents + 8))


def test_toggle_sends_tuner_on_and_off(qtbot, pedal):
    w, t = pedal
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    assert w.tuner_panel.isVisible() or not w.isVisible()
    w.tuner_button.click()
    qtbot.waitUntil(lambda: OFF in sent_sysex(t), timeout=3000)
    w.close()


def test_shortcut_t_toggles_tuner(qtbot, pedal):
    w, t = pedal
    # the offscreen platform never activates a window, so key events cannot reach shortcuts: emit it
    assert w.tuner_shortcut.key().toString() == "T"
    w.tuner_shortcut.activated.emit()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    assert w.tuner_button.isChecked()
    w.tuner_shortcut.activated.emit()
    qtbot.waitUntil(lambda: OFF in sent_sysex(t), timeout=3000)
    assert not w.tuner_button.isChecked()
    w.close()


def test_readings_are_shown_in_the_panel(qtbot, pedal):
    w, t = pedal
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    reading(t, 3, 0)  # C, in tune
    qtbot.waitUntil(lambda: w.tuner_panel.note_text() == "C" and w.tuner_panel.state == "in_tune", timeout=3000)
    assert w.tuner_panel.offset_text() == "0"
    reading(t, 3, 4)
    qtbot.waitUntil(lambda: w.tuner_panel.offset_text() == "+4", timeout=3000)
    assert w.tuner_panel.state == "off"
    reading(t, 3, -2)
    qtbot.waitUntil(lambda: w.tuner_panel.offset_text() == "-2", timeout=3000)
    w.close()


def test_note_12_means_no_note(qtbot, pedal):
    w, t = pedal
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    reading(t, 8, 0)
    qtbot.waitUntil(lambda: w.tuner_panel.note_text() == "F", timeout=3000)
    reading(t, 12, 0)
    qtbot.waitUntil(lambda: w.tuner_panel.note_text() == "—", timeout=3000)
    assert w.tuner_panel.state == "none"
    w.close()


def test_editing_is_disabled_while_tuner_is_on(qtbot, pedal):
    w, t = pedal
    w.select_location(2)
    assert w.name_edit.isEnabled() and w.patch_list.isEnabled()
    w.tuner_button.click()
    assert not w.name_edit.isEnabled() and not w.patch_list.isEnabled()
    assert not w.catalog_panel.isEnabled() and not w.save_button.isEnabled()
    assert not w.backup_action.isEnabled()
    w.tuner_button.click()
    assert w.name_edit.isEnabled() and w.patch_list.isEnabled() and w.catalog_panel.isEnabled()
    assert w.backup_action.isEnabled()
    w.close()


def test_disconnect_with_tuner_on_sends_off_first(qtbot, pedal):
    w, t = pedal
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    with qtbot.waitSignal(w._worker.disconnected, timeout=3000):
        w.disconnect_button.click()
    assert OFF in sent_sysex(t) and t.closed
    assert not w.tuner_button.isChecked() and w.splitter.isEnabled() and not w.tuner_panel.isVisible()


def test_close_with_tuner_on_sends_off(qtbot, pedal):
    w, t = pedal
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    w.close()
    assert OFF in sent_sysex(t)


def test_patch_reads_work_after_tuner_off(qtbot, pedal):
    w, t = pedal
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    reading(t, 3, 1)
    qtbot.waitUntil(lambda: w.tuner_panel.note_text() == "C", timeout=3000)
    w.tuner_button.click()
    qtbot.waitUntil(lambda: OFF in sent_sysex(t), timeout=3000)
    reading(t, 4, 2)  # stray tuner traffic after off must not confuse the next request
    for loc, raw in enumerate([(BACKUP / "001.zptc").read_bytes(), HB], start=1):  # replies for the second read
        t.on(sysex.header(0x6E) + b"\x46", SysexMessage(patch_reply(0, loc - 1, raw)))
    w.reload()
    qtbot.waitUntil(lambda: w.patch_list.item(1).text().split()[1:3] == ["HB", "Jazz"], timeout=5000)
    assert w.patch_list.item(1).text().split()[1:3] == ["HB", "Jazz"]
    w.close()


def test_tuner_button_needs_a_connection(qtbot, catalog):
    w = MainWindow(catalog, a1_ids=None)
    qtbot.addWidget(w)
    assert not w.tuner_button.isEnabled()


def test_worker_emits_tuner_reading_signal(qtbot):
    t = fake_pedal([HB])
    t.on(HDR + b"\x50", SysexMessage(HDR + b"\x00\x00"))
    t.on(HDR + b"\x51", SysexMessage(HDR + b"\x00\x00"))
    worker = PedalWorker(lambda: t, timeout=0.2)
    worker.connect_pedal()
    got = []
    worker.tuner_reading.connect(lambda note, off: got.append((note, off)))
    worker.tuner_on()
    reading(t, 0, 3)
    qtbot.waitUntil(lambda: ("A", 3) in got, timeout=3000)
    worker.tuner_off()
    assert sent_sysex(t)[-2:] == [OFF, HDR + b"\x51"]
    worker.disconnect_pedal()


def test_tuner_runs_inside_editor_mode(qtbot, pedal):
    """The pedal only streams tuner CC 98/99 in editor mode (observed on a real A1 FOUR)."""
    w, t = pedal
    w.tuner_button.click()
    qtbot.waitUntil(lambda: ON in sent_sysex(t), timeout=3000)
    sent = sent_sysex(t)
    assert HDR + b"\x50" in sent and sent.index(HDR + b"\x50") < sent.index(ON)
    w.tuner_button.click()
    qtbot.waitUntil(lambda: HDR + b"\x51" in sent_sysex(t), timeout=3000)
    sent = sent_sysex(t)
    assert sent.index(OFF) < sent.index(HDR + b"\x51")
    w.close()


def test_tuner_pill_says_which_way_to_tune_without_relying_on_colour(qtbot):
    from jmc_guitar_zoom.ui.glass import BackdropRoot
    from jmc_guitar_zoom.ui.tuner import TunerPanel

    root = BackdropRoot()
    qtbot.addWidget(root)
    panel = TunerPanel(root)
    expected = {(None, 0): "Sin nota · tocar una cuerda", ("C", 0): "AFINADO",
                ("C", -1): "BAJO −1 · subir afinación", ("C", 4): "ALTO +4 · bajar afinación"}
    for (note, offset), text in expected.items():
        panel.show_reading(note, offset)
        assert panel.status_text() == text
    panel.show_reading("C", -2)
    assert panel.offset_text() == "-2" and panel.state == "near"
