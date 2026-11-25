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
        before = pedal.disk_usage().available
        if before < len(zd2) + MEMORY_MARGIN:
            raise EffectInstallError(
                f"not enough memory for {name}: {len(zd2):,} bytes plus {MEMORY_MARGIN:,} spare, "
                f"{before:,} available")
        backup = write_file_backup(backup_dir, FLST_NAME, original)

        pedal.write_file(name, zd2)
        if _read_back(pedal, name) != zd2:
            _quietly(pedal.delete_file, name)
            raise EffectInstallError(f"{name} failed its read-back check; the upload was deleted")
        _write_list(pedal, new_list, original)
        return EffectChange(name, True, backup, before, pedal.disk_usage().available)


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
            _write_list(pedal, new_list, original)
        if present:
            pedal.delete_file(name)
            if name in pedal.list_files():
                raise EffectInstallError(f"{name} is still on the pedal after deleting it")
        return EffectChange(name, False, backup, before, pedal.disk_usage().available)


def _write_list(pedal: FilePedal, new_list: bytes, original: bytes) -> None:
    pedal.write_file(FLST_NAME, new_list)
    if _read_back(pedal, FLST_NAME) == new_list:
        return
    _quietly(pedal.write_file, FLST_NAME, original)
    raise EffectInstallError(f"{FLST_NAME} failed its read-back check; the original list was written back")


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
