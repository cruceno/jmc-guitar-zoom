"""The app-side patch bank: one .zptc per entry plus an index, never overwritten, rebuilt when damaged."""
import json
from pathlib import Path

import pytest

from zoomstudio.patches import bank as bank_module
from zoomstudio.patches.bank import BankError, PatchBank
from zoomstudio.patches.library import empty_patch
from zoomstudio.patches.zptc import build_zptc, parse_zptc

FIXTURES = Path(__file__).parent / "fixtures"
HB = next(FIXTURES.glob("*.zptc")).read_bytes()


def named(name: str) -> bytes:
    patch = parse_zptc(HB)
    patch.name = name
    return build_zptc(patch)


def test_round_trip_keeps_bytes_and_metadata(tmp_path):
    store = PatchBank(tmp_path / "bank")
    data = named("Lead One")
    entry = store.add(data, origin=44, now="20261125-101500")
    assert (entry.name, entry.origin, entry.stored_at) == ("Lead One", 44, "20261125-101500")
    assert store.read(entry.id) == data
    assert (tmp_path / "bank" / entry.file).read_bytes() == data
    # a second object over the same folder sees the same entry (the index is on disk)
    again = PatchBank(tmp_path / "bank").list()
    assert [(e.id, e.name, e.origin, e.sha256) for e in again] == [(entry.id, "Lead One", 44, entry.sha256)]


def test_add_never_overwrites_an_existing_file(tmp_path):
    store = PatchBank(tmp_path)
    first = store.add(named("Same"), origin=10, now="20261125-101500")
    second = store.add(named("Same"), origin=11, now="20261125-101500")
    assert first.file != second.file
    assert store.read(first.id) != b"" and len(store.list()) == 2
    with pytest.raises(FileExistsError):
        bank_module.write_exclusive(tmp_path / first.file, b"x")
    assert store.read(first.id) == named("Same")


def test_corrupt_index_is_rebuilt_from_the_files(tmp_path):
    store = PatchBank(tmp_path)
    entry = store.add(named("Keep Me"), origin=20)
    (tmp_path / bank_module.INDEX_NAME).write_text("{ not json")
    rebuilt = PatchBank(tmp_path).list()
    assert [(e.id, e.name, e.sha256) for e in rebuilt] == [(entry.id, "Keep Me", entry.sha256)]
    assert rebuilt[0].origin is None  # the origin lived only in the lost index
    json.loads((tmp_path / bank_module.INDEX_NAME).read_text())  # and the index is valid again


def test_missing_index_is_rebuilt_and_foreign_files_are_ignored(tmp_path):
    store = PatchBank(tmp_path)
    store.add(named("A"), origin=10)
    (tmp_path / bank_module.INDEX_NAME).unlink()
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / "broken.zptc").write_bytes(b"junk")
    assert [e.name for e in PatchBank(tmp_path).list()] == ["A"]


def test_index_entry_without_its_file_is_dropped_and_file_without_entry_is_adopted(tmp_path):
    store = PatchBank(tmp_path)
    gone = store.add(named("Gone"), origin=10)
    (tmp_path / gone.file).unlink()
    (tmp_path / "20260101-000000-Extra.zptc").write_bytes(named("Extra"))
    assert [e.name for e in PatchBank(tmp_path).list()] == ["Extra"]


def test_read_refuses_a_file_that_no_longer_matches_its_hash(tmp_path):
    store = PatchBank(tmp_path)
    entry = store.add(named("Hash"), origin=10)
    (tmp_path / entry.file).write_bytes(named("Other"))
    with pytest.raises(BankError):
        store.read(entry.id)


def test_remove_deletes_file_and_entry_and_unknown_id_fails(tmp_path):
    store = PatchBank(tmp_path)
    entry = store.add(named("Bye"), origin=10)
    store.remove(entry.id)
    assert store.list() == [] and not (tmp_path / entry.file).exists()
    with pytest.raises(BankError):
        store.remove(entry.id)


def test_add_rejects_bytes_that_are_not_a_patch(tmp_path):
    with pytest.raises(BankError):
        PatchBank(tmp_path).add(b"nope", origin=10)
    assert list(tmp_path.glob("*.zptc")) == []


def test_default_folder_is_patches_bank_under_the_workspace():
    assert bank_module.default_dir().parts[-2:] == ("patches", "bank")


def test_empty_patch_can_be_stored(tmp_path):
    entry = PatchBank(tmp_path).add(build_zptc(empty_patch()), origin=10)
    assert entry.name == empty_patch().name
