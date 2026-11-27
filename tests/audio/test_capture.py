import numpy as np
import pytest

from jmc_guitar_zoom.audio.capture import AudioInput, describe, list_input_devices, to_mono


def interleave(*channels, dtype):
    return np.stack(channels, axis=1).astype(dtype).tobytes()


def test_each_sample_format_becomes_float_in_minus_one_to_one():
    assert to_mono(interleave([0, 255, 128], dtype=np.uint8), "uint8", 1, 0).tolist() == \
        pytest.approx([-1.0, 127 / 128, 0.0])
    assert to_mono(interleave([-32768, 16384, 0], dtype=np.int16), "int16", 1, 0).tolist() == \
        pytest.approx([-1.0, 0.5, 0.0])
    assert to_mono(interleave([-2147483648, 1073741824], dtype=np.int32), "int32", 1, 0).tolist() == \
        pytest.approx([-1.0, 0.5])
    assert to_mono(interleave([0.25, -0.75], dtype=np.float32), "float", 1, 0).tolist() == \
        pytest.approx([0.25, -0.75])
    assert to_mono(interleave([1, 2], dtype=np.int16), "int16", 1, 0).dtype == np.float32


def test_the_chosen_channel_is_taken_from_interleaved_frames():
    data = interleave([0.1, 0.2, 0.3], [-0.1, -0.2, -0.3], [0.5, 0.5, 0.5], dtype=np.float32)
    assert to_mono(data, "float", 3, 0).tolist() == pytest.approx([0.1, 0.2, 0.3])
    assert to_mono(data, "float", 3, 1).tolist() == pytest.approx([-0.1, -0.2, -0.3])
    assert to_mono(data, "float", 3, 2).tolist() == pytest.approx([0.5, 0.5, 0.5])


def test_a_trailing_partial_frame_is_dropped():
    data = interleave([1000, 2000], [3000, 4000], dtype=np.int16) + b"\x01\x02"
    assert to_mono(data, "int16", 2, 1).tolist() == pytest.approx([3000 / 32768, 4000 / 32768])


def test_bad_channel_or_format_is_refused():
    with pytest.raises(ValueError):
        to_mono(b"\x00" * 8, "float", 2, 2)
    with pytest.raises(ValueError):
        to_mono(b"\x00" * 8, "int24", 2, 0)


class FakeFormat:
    def __init__(self, rate):
        self._rate = rate

    def sampleRate(self):  # noqa: N802 (Qt API)
        return self._rate


class FakeId:
    def __init__(self, value):
        self._value = value

    def data(self):
        return self._value


class FakeDevice:
    def __init__(self, ident, name, channels, rate):
        self._id, self._name, self._channels, self._rate = ident, name, channels, rate

    def id(self):
        return FakeId(self._id)

    def description(self):
        return self._name

    def maximumChannelCount(self):  # noqa: N802
        return self._channels

    def preferredFormat(self):  # noqa: N802
        return FakeFormat(self._rate)


def test_describe_reads_name_channels_rate_and_default():
    card = describe(FakeDevice(b"usb-card", "Any USB card", 4, 96000), default_id="usb-card")
    assert (card.id, card.name, card.channels, card.sample_rate, card.is_default) == \
        ("usb-card", "Any USB card", 4, 96000, True)
    assert not describe(FakeDevice(b"pci", "Built-in", 2, 48000), default_id="usb-card").is_default


def test_listing_and_opening_need_qt_multimedia(qtbot):
    pytest.importorskip("PySide6.QtMultimedia")
    devices = list_input_devices()
    assert all(d.channels >= 1 and d.sample_rate > 0 for d in devices)
    assert [d.is_default for d in devices] == sorted((d.is_default for d in devices), reverse=True)
    audio = AudioInput()
    with qtbot.waitSignal(audio.failed, timeout=1000):
        assert audio.start("no-such-device", 0) is False
    assert not audio.running
