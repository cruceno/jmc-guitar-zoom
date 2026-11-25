"""Tuner off must always leave editor mode, even when the pedal errors (verifier B3)."""
from contextlib import contextmanager

from zoomstudio.device.errors import PedalTimeout
from zoomstudio.ui.worker import PedalWorker


class FakeClient:
    def __init__(self, fail: set[str] = frozenset()):
        self.calls: list[tuple[str, bool]] = []
        self.fail = set(fail)

    @contextmanager
    def pc_mode(self, on=True):
        self.calls.append(("pc", on))
        try:
            yield
        finally:
            self.calls.append(("pc", False))

    def editor_mode(self, on):
        self.calls.append(("ed", on))

    def tuner(self, on):
        self.calls.append(("tuner", on))
        if not on and "tuner_off" in self.fail:
            raise PedalTimeout("tuner off lost")

    def subscribe(self, callback):
        return lambda: None

    def poll(self, timeout):
        raise PedalTimeout("port gone")


def worker_with(client):
    worker = PedalWorker(lambda: None)
    worker._client = client
    return worker


def test_tuner_on_then_off_pairs_editor_mode(qapp):
    client = FakeClient()
    worker = worker_with(client)
    worker.tuner_on()
    worker.tuner_off()
    assert client.calls == [("ed", True), ("tuner", True), ("tuner", False), ("ed", False)]


def test_failed_tuner_off_still_leaves_editor_mode(qapp):
    client = FakeClient()
    worker = worker_with(client)
    worker.tuner_on()
    client.fail.add("tuner_off")
    errors = []
    worker.error.connect(lambda *a: errors.append(a))
    worker.tuner_off()
    assert client.calls[-1] == ("ed", False) and errors


def test_poll_error_leaves_editor_mode(qapp):
    client = FakeClient()
    worker = worker_with(client)
    worker.tuner_on()
    states = []
    worker.tuner_state.connect(states.append)
    worker._poll_tuner()
    assert client.calls[-1] == ("ed", False) and states[-1] is False
