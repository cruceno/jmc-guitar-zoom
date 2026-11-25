"""The app-side patch bank: one .zptc per entry plus an index, never overwritten, rebuilt when damaged."""
import json
from pathlib import Path

import pytest

from zoomstudio.patches import bank as bank_module
from zoomstudio.patches.bank import BankError, PatchBank
from zoomstudio.patches.library import empty_patch
from zoomstudio.patches.zptc import build_zptc, parse_zptc

from fixture_files import PATCHES as FIXTURES  # noqa: E402

HB = (FIXTURES / "53-HB-Jazz.zptc").read_bytes()


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


# ------------------------------------------------------------ rename and delete

def test_rename_changes_the_patch_and_the_index_and_trashes_the_old_file(tmp_path):
    store = PatchBank(tmp_path)
    old = store.add(named("Old Name"), origin=44, now="20261125-101500")
    new = store.rename(old.id, "New Name")
    assert (new.name, new.origin, new.stored_at) == ("New Name", 44, "20261125-101500")
    assert new.id != old.id and new.sha256 != old.sha256
    assert parse_zptc(store.read(new.id)).name == "New Name"
    assert [e.id for e in PatchBank(tmp_path).list()] == [new.id]
    trashed = list(store.trash_dir().glob("*.zptc"))
    assert len(trashed) == 1 and parse_zptc(trashed[0].read_bytes()).name == "Old Name"
    assert not (tmp_path / old.file).exists()


def test_rename_to_a_colliding_name_never_overwrites(tmp_path):
    store = PatchBank(tmp_path)
    a = store.add(named("Same"), origin=10, now="20261125-101500")
    b = store.add(named("Other"), origin=11, now="20261125-101500")
    renamed = store.rename(b.id, "Same")
    assert renamed.file != a.file and store.read(a.id) == named("Same")
    assert len(store.list()) == 2


@pytest.mark.parametrize("bad", ["Eleven char", "Ñandú", "tab\there"])
def test_rename_refuses_names_the_editor_would_refuse(tmp_path, bad):
    store = PatchBank(tmp_path)
    entry = store.add(named("Keep"), origin=10)
    with pytest.raises(BankError):
        store.rename(entry.id, bad)
    assert [e.name for e in store.list()] == ["Keep"] and not store.trash_dir().exists()


def test_delete_moves_the_file_to_the_trash_and_it_is_never_readopted(tmp_path):
    store = PatchBank(tmp_path)
    entry = store.add(named("Gone"), origin=10)
    trashed = store.delete(entry.id)
    assert trashed.parent == store.trash_dir() and trashed.read_bytes() == named("Gone")
    assert store.list() == [] and not (tmp_path / entry.file).exists()
    (tmp_path / bank_module.INDEX_NAME).unlink()  # even a rebuilt index does not bring it back
    assert PatchBank(tmp_path).list() == []
    again = store.add(named("Gone"), origin=10, now=entry.stored_at)
    assert len(list(store.trash_dir().glob("*.zptc"))) == 1 and store.delete(again.id) != trashed
    assert len(list(store.trash_dir().glob("*.zptc"))) == 2


def test_delete_and_rename_of_an_unknown_or_missing_entry_fail_cleanly(tmp_path):
    store = PatchBank(tmp_path)
    entry = store.add(named("Lost"), origin=10)
    (tmp_path / entry.file).unlink()
    for call in (lambda: store.delete(entry.id), lambda: store.rename(entry.id, "X"), lambda: store.delete("nope")):
        with pytest.raises(BankError):
            call()
