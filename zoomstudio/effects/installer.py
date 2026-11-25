"""Install and remove effects on the pedal, replicating what Guitar Lab does.

Guitar Lab installs an effect by uploading its ``.ZD2`` file unchanged and setting
its flag in ``FLST_SEQ.ZT2`` (see :mod:`zoomstudio.effects.flst`). Both steps here
are verified by reading the file back, and the list is backed up first.

Order keeps the list from pointing at a missing file: install uploads the effect
before setting the flag; remove clears the flag before deleting the effect.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from zoomstudio.device.errors import PedalError, PedalFileNotFound
from zoomstudio.device.sysex import DiskUsage
from zoomstudio.patches.backup import write_file_backup

from . import flst
from .flst import FLST_NAME

# Uploading 27,864 bytes took 28,630 bytes of pedal memory; keep a block's margin on top.
MEMORY_MARGIN = 4096


class EffectInstallError(RuntimeError):
    """The install or removal was refused or failed; the message says which and why."""


class FilePedal(Protocol):
    def pc_mode(self, on: bool = True): ...
    def list_files(self) -> list[str]: ...
    def read_file(self, name: str) -> bytes: ...
    def write_file(self, name: str, data: bytes) -> None: ...
    def delete_file(self, name: str) -> None: ...
    def disk_usage(self) -> DiskUsage: ...


@dataclass(frozen=True)
class EffectChange:
    name: str
    installed: bool
    backup: Path  # FLST_SEQ.ZT2 as it was before the change
    available_before: int
    available_after: int


def install_effect(pedal: FilePedal, zd2: bytes, name: str, backup_dir: Path) -> EffectChange:
    """Upload ``zd2`` as ``name`` and mark it installed."""
    name = name.upper()
    with pedal.pc_mode(True):
        original = pedal.read_file(FLST_NAME)
        try:
            if flst.is_installed(original, name):
                raise EffectInstallError(f"{name} is already installed")
            new_list = flst.set_installed(original, name, True)
        except flst.FlstError as exc:
            raise EffectInstallError(str(exc)) from exc
        before = _check_memory(pedal, name, zd2)
        backup = write_file_backup(backup_dir, FLST_NAME, original)
        _upload_effect(pedal, name, zd2)
        _write_list(pedal, new_list, original, backup)
        return EffectChange(name, True, backup, before, pedal.disk_usage().available)


def repair_effect(pedal: FilePedal, zd2: bytes, name: str, backup_dir: Path) -> EffectChange:
    """Upload the missing file of an effect the list already marks installed; the list is not changed.

    Found on a real A1 FOUR: ``B_OCTAVE.ZD2`` was flagged installed while its file was absent.
    """
    name = name.upper()
    with pedal.pc_mode(True):
        original = pedal.read_file(FLST_NAME)
        try:
            listed = flst.is_installed(original, name)
        except flst.FlstError as exc:
            raise EffectInstallError(str(exc)) from exc
        if not listed:
            raise EffectInstallError(f"{name} is not marked installed; install it instead")
        if name in pedal.list_files():
            raise EffectInstallError(f"{name} is already on the pedal; nothing to repair")
        before = _check_memory(pedal, name, zd2)
        backup = write_file_backup(backup_dir, FLST_NAME, original)  # same audit trail as install
        _upload_effect(pedal, name, zd2)
        return EffectChange(name, True, backup, before, pedal.disk_usage().available)


def _check_memory(pedal: FilePedal, name: str, zd2: bytes) -> int:
    available = pedal.disk_usage().available
    if available < len(zd2) + MEMORY_MARGIN:
        raise EffectInstallError(
            f"not enough memory for {name}: {len(zd2):,} bytes plus {MEMORY_MARGIN:,} spare, "
            f"{available:,} available")
    return available


def _upload_effect(pedal: FilePedal, name: str, zd2: bytes) -> None:
    """Upload and read back; never leave a partial or wrong effect taking pedal memory."""
    try:
        pedal.write_file(name, zd2)
    except PedalError as exc:
        _quietly(pedal.delete_file, name)
        raise EffectInstallError(f"the upload of {name} failed ({exc}); the partial file was deleted") from exc
    if _read_back(pedal, name) != zd2:
        _quietly(pedal.delete_file, name)
        raise EffectInstallError(f"{name} failed its read-back check; the upload was deleted")


def remove_effect(pedal: FilePedal, name: str, backup_dir: Path,
                  in_use: Mapping[str, Sequence[int]] | None = None) -> EffectChange:
    """Clear the flag of ``name`` and delete its file. ``in_use`` maps names to patches using them."""
    name = name.upper()
    users = (in_use or {}).get(name)
    if users:
        raise EffectInstallError(f"{name} is used by patch(es) {', '.join(map(str, users))}")
    with pedal.pc_mode(True):
        original = pedal.read_file(FLST_NAME)
        try:
            listed = flst.is_installed(original, name)
            new_list = flst.set_installed(original, name, False)
        except flst.FlstError as exc:
            raise EffectInstallError(str(exc)) from exc
        present = name in pedal.list_files()
        if not listed and not present:
            raise EffectInstallError(f"{name} is not installed")
        before = pedal.disk_usage().available
        backup = write_file_backup(backup_dir, FLST_NAME, original)

        if listed:
            _write_list(pedal, new_list, original, backup)
        if present:
            pedal.delete_file(name)
            if name in pedal.list_files():
                raise EffectInstallError(f"{name} is still on the pedal after deleting it")
        return EffectChange(name, False, backup, before, pedal.disk_usage().available)


RESTORE_ATTEMPTS = 3


def _write_list(pedal: FilePedal, new_list: bytes, original: bytes, backup: Path) -> None:
    """Write the new list and read it back; on any failure put the original back.

    ``write_file`` deletes the old file before uploading, so a failed upload leaves the
    pedal with a truncated list or none: the original is restored before raising, and
    the error names the backup when even that fails.
    """
    try:
        pedal.write_file(FLST_NAME, new_list)
        problem = None if _read_back(pedal, FLST_NAME) == new_list else "failed its read-back check"
    except PedalError as exc:
        problem = f"upload failed ({exc})"
    if problem is None:
        return
    if _restore(pedal, original):
        raise EffectInstallError(f"{FLST_NAME} {problem}; the original list was restored")
    raise EffectInstallError(
        f"{FLST_NAME} {problem} and the original list could not be restored: "
        f"upload the backup {backup} as {FLST_NAME} before using the pedal's effects")


def _restore(pedal: FilePedal, original: bytes) -> bool:
    for _ in range(RESTORE_ATTEMPTS):
        try:
            pedal.write_file(FLST_NAME, original)
            if _read_back(pedal, FLST_NAME) == original:
                return True
        except PedalError:
            continue
    return False


def _read_back(pedal: FilePedal, name: str) -> bytes | None:
    try:
        return pedal.read_file(name)
    except PedalFileNotFound:
        return None


def _quietly(action, *args) -> None:
    try:
        action(*args)
    except PedalError:
        pass  # the caller reports the original failure
