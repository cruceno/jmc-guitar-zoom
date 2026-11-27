"""Sound-card input for the tuner: any input device Qt lists, one of its channels, as mono float samples.

Nothing here is tied to one card: the device's preferred sample rate and sample format are used as they
are (8/16/32-bit integers or floats), and every format becomes float32 in -1..1. QtMultimedia is imported
only when a device is listed or opened, so the editor still starts where it cannot load (no PulseAudio
client library, for example); the tuner then says that no audio input is available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

# sample format name -> (numpy dtype, offset, scale): float = (raw - offset) / scale
FORMATS = {
    "uint8": (np.uint8, 128.0, 128.0),
    "int16": (np.int16, 0.0, 32768.0),
    "int32": (np.int32, 0.0, 2147483648.0),
    "float": (np.float32, 0.0, 1.0),
}


@dataclass(frozen=True)
class InputDevice:
    id: str
    name: str
    channels: int
    sample_rate: int
    is_default: bool = False


def to_mono(data: bytes, sample_format: str, channels: int, channel: int) -> np.ndarray:
    """One channel of interleaved ``data`` as float32 in -1..1 (a trailing partial frame is dropped)."""
    if sample_format not in FORMATS:
        raise ValueError(f"unsupported sample format {sample_format!r}")
    if not 0 <= channel < channels:
        raise ValueError(f"channel {channel} outside 0..{channels - 1}")
    dtype, offset, scale = FORMATS[sample_format]
    width = np.dtype(dtype).itemsize * channels
    usable = len(data) - len(data) % width
    raw = np.frombuffer(data[:usable], dtype=dtype).reshape(-1, channels)[:, channel]
    return ((raw.astype(np.float32) - offset) / scale).astype(np.float32)


def _format_name(sample_format) -> str | None:
    name = getattr(sample_format, "name", str(sample_format)).split(".")[-1].lower()
    return name if name in FORMATS else None


def _device_id(device) -> str:
    return bytes(device.id().data()).decode("utf-8", "replace")


def describe(device, default_id: str | None = None) -> InputDevice:
    """An InputDevice from a QAudioDevice (or anything with the same methods)."""
    preferred = device.preferredFormat()
    device_id = _device_id(device)
    return InputDevice(device_id, device.description(), max(1, int(device.maximumChannelCount())),
                       int(preferred.sampleRate()), device_id == default_id)


def _multimedia():
    try:
        from PySide6 import QtMultimedia
    except ImportError as exc:  # the module or one of its system libraries is missing
        log.warning("QtMultimedia unavailable: %s", exc)
        return None
    return QtMultimedia


def list_input_devices() -> list[InputDevice]:
    """The system's audio inputs, the default one first; empty when QtMultimedia cannot be loaded."""
    mm = _multimedia()
    if mm is None:
        return []
    default = mm.QMediaDevices.defaultAudioInput()
    default_id = _device_id(default) if not default.isNull() else None
    devices = [describe(d, default_id) for d in mm.QMediaDevices.audioInputs()]
    return sorted(devices, key=lambda d: not d.is_default)


class AudioInput(QObject):
    """Reads one channel of an input device and emits it as float32 blocks (on the thread it lives on)."""

    samples = Signal(object)  # numpy float32 array, mono
    failed = Signal(str)  # the device could not be opened or stopped delivering

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source = None
        self._io = None
        self._format = "float"
        self._channels = 1
        self._channel = 0
        self.sample_rate = 0
        self.device: InputDevice | None = None

    @property
    def running(self) -> bool:
        return self._source is not None

    def start(self, device_id: str, channel: int) -> bool:
        """Open ``device_id`` and deliver its ``channel`` (0-based). False, with ``failed`` emitted, on error."""
        self.stop()
        mm = _multimedia()
        if mm is None:
            self.failed.emit("QtMultimedia")
            return False
        device = next((d for d in mm.QMediaDevices.audioInputs() if _device_id(d) == device_id), None)
        if device is None:
            self.failed.emit(device_id)
            return False
        fmt = device.preferredFormat()
        if channel >= fmt.channelCount():
            wider = mm.QAudioFormat(fmt)
            wider.setChannelCount(min(device.maximumChannelCount(), max(channel + 1, fmt.channelCount())))
            if device.isFormatSupported(wider):
                fmt = wider
        name = _format_name(fmt.sampleFormat())
        if name is None or channel >= fmt.channelCount():
            self.failed.emit(device.description())
            return False
        source = mm.QAudioSource(device, fmt, self)
        io = source.start()
        if io is None:
            source.deleteLater()
            self.failed.emit(device.description())
            return False
        self._source, self._io = source, io
        self._format, self._channels, self._channel = name, fmt.channelCount(), channel
        self.sample_rate = fmt.sampleRate()
        self.device = describe(device)
        io.readyRead.connect(self._read)
        return True

    def stop(self) -> None:
        source, self._source, self._io = self._source, None, None
        if source is not None:
            source.stop()
            source.deleteLater()

    def _read(self) -> None:
        if self._io is None:
            return
        data = bytes(self._io.readAll().data())
        if data:
            self.samples.emit(to_mono(data, self._format, self._channels, self._channel))
