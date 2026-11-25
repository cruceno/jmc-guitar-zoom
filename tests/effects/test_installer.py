"""Install and remove effects on a fake pedal file system, through the installer's public functions."""

from contextlib import contextmanager
from pathlib import Path

import pytest

from zoomstudio.device.errors import PedalFileNotFound, PedalTimeout
from zoomstudio.device.sysex import DiskUsage
from zoomstudio.effects import installer

FIXTURES = Path(__file__).parent / "fixtures" / "flst"
BEFORE = (FIXTURES / "before-12st.ZT2").read_bytes()
AFTER = (FIXTURES / "after-12st.ZT2").read_bytes()
ZD2 = bytes(range(256)) * 100  # stands in for MDL_12ST.ZD2
NAME = "MDL_12ST.ZD2"


class FakePedal:
    """In-memory pedal file system; records whether writes happen inside PC mode."""

    def __init__(self, files: dict[str, bytes], available: int = 143150) -> None:
        self.files = dict(files)
        self.available = available
        self.pc = False
        self.writes: list[tuple[str, bool]] = []
        self.corrupt_next_read: str | None = None

    @contextmanager
    def pc_mode(self, on: bool = True):
        self.pc = True
        try:
            yield
        finally:
            self.pc = False

    def list_files(self):
        return sorted(self.files)

    def read_file(self, name):
        if name not in self.files:
            raise PedalFileNotFound(name)
        data = self.files[name]
        if self.corrupt_next_read == name:
            self.corrupt_next_read = None
            return data[:-1] + bytes([data[-1] ^ 1])
        return data

    def write_file(self, name, data):
        self.writes.append((name, self.pc))
        self.available += len(self.files.get(name, b""))
        self.files[name] = bytes(data)
        self.available -= len(data)

    def delete_file(self, name):
        self.writes.append((f"delete {name}", self.pc))
        self.available += len(self.files.pop(name, b""))

    def disk_usage(self):
        return DiskUsage(maximum=3087950, available=self.available)


def test_install_writes_the_effect_then_the_flag(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": BEFORE})
    result = installer.install_effect(pedal, ZD2, NAME, tmp_path)
    assert pedal.files["FLST_SEQ.ZT2"] == AFTER
    assert pedal.files[NAME] == ZD2
    assert [w for w, _ in pedal.writes] == [NAME, "FLST_SEQ.ZT2"]
    assert all(in_pc for _, in_pc in pedal.writes)
    assert result.backup.read_bytes() == BEFORE and result.backup.parent == tmp_path
    assert result.available_after == result.available_before - len(ZD2)


def test_install_refuses_when_memory_is_short(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": BEFORE}, available=len(ZD2))
    with pytest.raises(installer.EffectInstallError, match="memory"):
        installer.install_effect(pedal, ZD2, NAME, tmp_path)
    assert pedal.writes == [] and pedal.files == {"FLST_SEQ.ZT2": BEFORE}


def test_install_refuses_an_installed_effect(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": AFTER, NAME: ZD2})
    with pytest.raises(installer.EffectInstallError, match="already installed"):
        installer.install_effect(pedal, ZD2, NAME, tmp_path)
    assert pedal.writes == []


def test_install_refuses_an_effect_missing_from_the_list(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": BEFORE})
    with pytest.raises(installer.EffectInstallError):
        installer.install_effect(pedal, ZD2, "NOPE.ZD2", tmp_path)
    assert pedal.writes == []


def test_bad_effect_read_back_deletes_it_and_keeps_the_list(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": BEFORE})
    pedal.corrupt_next_read = NAME
    with pytest.raises(installer.EffectInstallError, match="read-back"):
        installer.install_effect(pedal, ZD2, NAME, tmp_path)
    assert NAME not in pedal.files and pedal.files["FLST_SEQ.ZT2"] == BEFORE


def test_bad_list_read_back_restores_the_original_list(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": BEFORE})
    original_write = pedal.write_file

    def write_then_corrupt(name, data):
        original_write(name, data)
        if name == "FLST_SEQ.ZT2" and data == AFTER:
            pedal.corrupt_next_read = "FLST_SEQ.ZT2"

    pedal.write_file = write_then_corrupt
    with pytest.raises(installer.EffectInstallError, match="read-back"):
        installer.install_effect(pedal, ZD2, NAME, tmp_path)
    assert pedal.files["FLST_SEQ.ZT2"] == BEFORE


def test_remove_clears_the_flag_then_deletes_the_effect(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": AFTER, NAME: ZD2})
    result = installer.remove_effect(pedal, NAME, tmp_path)
    assert pedal.files == {"FLST_SEQ.ZT2": BEFORE}
    assert [w for w, _ in pedal.writes] == ["FLST_SEQ.ZT2", f"delete {NAME}"]
    assert all(in_pc for _, in_pc in pedal.writes)
    assert result.backup.read_bytes() == AFTER
    assert result.available_after == result.available_before + len(ZD2)


def test_remove_refuses_an_effect_used_by_a_patch(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": AFTER, NAME: ZD2})
    with pytest.raises(installer.EffectInstallError, match="used by"):
        installer.remove_effect(pedal, NAME, tmp_path, in_use={NAME: [53]})
    assert pedal.writes == []


def test_remove_refuses_an_effect_that_is_not_installed(tmp_path):
    pedal = FakePedal({"FLST_SEQ.ZT2": BEFORE})
    with pytest.raises(installer.EffectInstallError, match="not installed"):
        installer.remove_effect(pedal, NAME, tmp_path)
    assert pedal.writes == []


class FlakyPedal(FakePedal):
    """Times out part-way through uploading ``fail_on`` (leaving the first block), like a dropped transfer."""

    def __init__(self, files, fail_on: str, failures: int = 1, **kw):
        super().__init__(files, **kw)
        self.fail_on, self.failures = fail_on, failures

    def write_file(self, name, data):
        if name == self.fail_on and self.failures:
            self.failures -= 1
            self.writes.append((name, self.pc))
            self.files[name] = bytes(data[:512])
            raise PedalTimeout("mid-upload")
        super().write_file(name, data)


def test_list_upload_timeout_restores_the_original_list(tmp_path):
    # verifier B1: a failed FLST_SEQ upload must not leave the pedal with a truncated list
    pedal = FlakyPedal({"FLST_SEQ.ZT2": BEFORE}, fail_on="FLST_SEQ.ZT2")
    with pytest.raises(installer.EffectInstallError, match="restored"):
        installer.install_effect(pedal, ZD2, NAME, tmp_path)
    assert pedal.files["FLST_SEQ.ZT2"] == BEFORE


def test_list_restore_failure_names_the_backup(tmp_path):
    pedal = FlakyPedal({"FLST_SEQ.ZT2": BEFORE}, fail_on="FLST_SEQ.ZT2", failures=99)
    with pytest.raises(installer.EffectInstallError) as caught:
        installer.install_effect(pedal, ZD2, NAME, tmp_path)
    backup = next(tmp_path.iterdir())
    assert str(backup) in str(caught.value) and backup.read_bytes() == BEFORE


def test_effect_upload_timeout_deletes_the_partial_file(tmp_path):
    # verifier B2: a failed effect upload must not leave a partial .ZD2 taking pedal memory
    pedal = FlakyPedal({"FLST_SEQ.ZT2": BEFORE}, fail_on=NAME)
    with pytest.raises(installer.EffectInstallError, match="upload"):
        installer.install_effect(pedal, ZD2, NAME, tmp_path)
    assert NAME not in pedal.files and pedal.files["FLST_SEQ.ZT2"] == BEFORE


def test_remove_list_upload_timeout_restores_the_original_list(tmp_path):
    pedal = FlakyPedal({"FLST_SEQ.ZT2": AFTER, NAME: ZD2}, fail_on="FLST_SEQ.ZT2")
    with pytest.raises(installer.EffectInstallError, match="restored"):
        installer.remove_effect(pedal, NAME, tmp_path)
    assert pedal.files == {"FLST_SEQ.ZT2": AFTER, NAME: ZD2}
