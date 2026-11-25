"""A failing subscriber must not break requests (verifier blocker B1)."""

import logging

from device_replies import HDR
from jmc_guitar_zoom.device.client import PedalClient
from jmc_guitar_zoom.device.messages import ControlChange, SysexMessage
from jmc_guitar_zoom.device.transport import FakeTransport

PATCH_INFO = HDR + bytes([0x43, 0x32, 0x00, 0x78, 0x05, 0x32, 0x00, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00])


def test_raising_subscriber_does_not_break_requests(caplog):
    t = FakeTransport()
    c = PedalClient(t, timeout=0.2)
    seen = []
    c.subscribe(lambda event: 1 / 0)
    c.subscribe(seen.append)
    for _ in range(3):
        t.on(HDR + b"\x44", ControlChange(98, 1), SysexMessage(PATCH_INFO))
    with caplog.at_level(logging.ERROR, logger="jmc_guitar_zoom.device.client"):
        results = [c.patch_info() for _ in range(3)]
    assert [r.count for r in results] == [50, 50, 50]
    assert len(seen) == 3  # the healthy subscriber still gets every tuner event
    assert "subscriber" in caplog.text.lower()
