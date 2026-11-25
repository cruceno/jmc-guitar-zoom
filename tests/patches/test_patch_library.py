import pytest

from zoomstudio.patches import edit
from zoomstudio.patches.library import (
    EMPTY_PATCH_FILE, empty_patch, export_one, export_patches, new_folder, read_folder,
)
from zoomstudio.patches.model import EffectSlot
from zoomstudio.patches.zptc import build_zptc, parse_zptc


class Info:
    def __init__(self, name, wide=False, dsp=10.0):
        self.name, self.is_wide, self.dsp_load_percent = name, wide, dsp


CATALOG = {0x10: Info("Comp"), 0x20: Info("Wide", wide=True, dsp=5.0)}


def patch_with(*ids):
    p = empty_patch()
    p.effects = [EffectSlot(effect_id=i) for i in ids]
    return p


def test_empty_resource_is_the_factory_empty_patch():
    assert len(EMPTY_PATCH_FILE.read_bytes()) == 760
    p = empty_patch()
    assert p.name == "Empty" and all(s.is_empty for s in p.effects)
    assert parse_zptc(build_zptc(p)) == p  # the file's trailing residue is not part of the patch


def test_slot_problems_flag_unknown_and_non_a1_effects():
    p = patch_with(0x10, 0x20, 0x99, 0x0)
    assert edit.slot_problems(p, CATALOG, None) == {2: edit.UNKNOWN_EFFECT_REASON}
    assert edit.slot_problems(p, CATALOG, {0x10}) == {1: edit.NOT_RUNNABLE_REASON, 2: edit.UNKNOWN_EFFECT_REASON}


def test_save_blockers_cover_unknown_dsp_and_slot_cap():
    assert edit.save_blockers(patch_with(0x10, 0x20), CATALOG, None) == []
    assert edit.UNKNOWN_EFFECT_REASON in edit.save_blockers(patch_with(0x99), CATALOG, None)[0]
    assert "carga de DSP es 110 %" in edit.save_blockers(patch_with(*[0x10] * 11), CATALOG, None)[0]
    nine_wide = edit.save_blockers(patch_with(*[0x20] * 9), CATALOG, None)  # 18 slots with fillers
    assert len(nine_wide) == 1 and "18 slots" in nine_wide[0]


def test_new_folder_never_reuses_a_folder(tmp_path):
    first = new_folder(tmp_path, "backup", "20260101-000000")
    assert first.name == "backup-20260101-000000"
    with pytest.raises(FileExistsError):
        new_folder(tmp_path, "backup", "20260101-000000")


def test_export_and_read_back_round_trip(tmp_path):
    a = patch_with(0x10)
    a.name = "Alpha"
    folder = export_patches(tmp_path, {3: a, 7: empty_patch()}, "20260101-000001")
    found, problems = read_folder(folder)
    assert problems == [] and sorted(found) == [3, 7] and found[3].name == "Alpha"
    one = export_one(tmp_path, 5, a)
    assert one.name == "005-Alpha.zptc" and parse_zptc(one.read_bytes()).name == "Alpha"
    with pytest.raises(FileExistsError):
        export_one(tmp_path, 5, a)
    (tmp_path / "bad.zptc").write_bytes(b"x")
    (folder / "009.zptc").write_bytes(b"junk")
    found, problems = read_folder(folder)
    assert 9 not in found and problems and "009.zptc" in problems[0]


def test_save_blockers_report_effects_missing_from_the_pedal_only_when_its_list_is_known():
    patch = patch_with(0x10, 0x20, 0x10)
    assert edit.not_installed_slots(patch, CATALOG, None) == []  # nothing known: nothing guessed
    assert edit.save_blockers(patch, CATALOG, None, None) == edit.save_blockers(patch, CATALOG, None)
    assert edit.not_installed_slots(patch, CATALOG, {0x10, 0x20}) == []
    assert edit.save_blockers(patch, CATALOG, None, {0x10, 0x20}) == []
    missing = edit.not_installed_slots(patch, CATALOG, {0x20})
    assert [patch.effects[i].effect_id for i in missing] == [0x10, 0x10]
    reasons = edit.save_blockers(patch, CATALOG, None, {0x20})
    assert reasons == [f"El patch usa efectos que no están en la pedalera: {CATALOG[0x10].name}"]
    assert edit.slot_problems(patch, CATALOG, None) == {}  # the tile's red state is a different thing
