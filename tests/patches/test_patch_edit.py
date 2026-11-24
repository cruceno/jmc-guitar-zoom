from pathlib import Path

import pytest

from zoomstudio.effects.catalog import load_catalog
from zoomstudio.patches import edit
from zoomstudio.patches.model import WIDE_FILLER_ID
from zoomstudio.patches.zptc import parse_zptc

UI_FIX = Path(__file__).parents[1] / "ui" / "fixtures"
HB = parse_zptc((UI_FIX / "53-HB-Jazz.zptc").read_bytes())
CATALOG = load_catalog(("pedal", UI_FIX / "catalog"))
COMP, DLXR, HALL, GEQ = 0x1000010, 0x400002C, 0x9000030, 0x2000054


def ids(patch):
    return [s.effect_id for s in patch.effects]


def test_sent_form_strips_wide_fillers_only():
    sent = edit.sent_form(HB)
    assert WIDE_FILLER_ID in ids(HB)
    assert ids(sent) == [0x1000080, DLXR, 0x500002A, GEQ, HALL]
    assert ids(HB).count(WIDE_FILLER_ID) == 2  # the original is untouched


def test_sent_form_keeps_empty_slots():
    patch = edit.remove_effect(HB, 3, CATALOG)
    assert 0 in ids(edit.sent_form(patch))


def test_with_fillers_reinserts_after_wide_effects():
    sent = edit.sent_form(HB)
    assert ids(edit.with_fillers(sent, CATALOG)) == ids(HB)


def test_replace_effect_uses_catalog_defaults_including_dummies():
    patch = edit.replace_effect(HB, 6, DLXR, CATALOG)  # Hall -> FD DLXR (wide)
    assert ids(patch)[-2:] == [DLXR, WIDE_FILLER_ID]
    slot = patch.effects[6]
    assert slot.enabled is True
    assert slot.params[:7] == [0, 33, 55, 50, 90, 0, 40]
    assert slot.params[7:] == [0] * 5  # dummy params keep their ELF defaults (0 here)
    assert ids(HB)[6] == HALL


def test_replace_wide_by_narrow_drops_filler():
    patch = edit.replace_effect(HB, 1, COMP, CATALOG)
    assert ids(patch) == [0x1000080, COMP, 0x500002A, GEQ, WIDE_FILLER_ID, HALL]


def test_replace_beyond_the_chain_pads_with_empty_slots():
    patch = edit.replace_effect(HB, len(HB.effects) + 1, COMP, CATALOG)
    assert ids(patch)[-3:] == [HALL, 0, COMP]


def test_remove_effect_leaves_an_empty_slot_and_trims_the_tail():
    patch = edit.remove_effect(HB, 1, CATALOG)
    assert ids(patch) == [0x1000080, 0, 0x500002A, GEQ, WIDE_FILLER_ID, HALL]
    assert ids(edit.remove_effect(HB, 6, CATALOG))[-1] == WIDE_FILLER_ID  # trailing empty is trimmed


def test_move_effect_reorders_logical_positions():
    patch = edit.move_effect(HB, 6, 0, CATALOG)  # Hall to the front
    assert ids(patch) == [HALL, 0x1000080, DLXR, WIDE_FILLER_ID, 0x500002A, GEQ, WIDE_FILLER_ID]


def test_rename_volume_param_enabled():
    patch = edit.rename(HB, "New Name")
    assert patch.name == "New Name"
    with pytest.raises(ValueError):
        edit.rename(HB, "01234567890")
    with pytest.raises(ValueError):
        edit.rename(HB, "café")
    assert edit.set_volume(HB, 64).volume == 64
    with pytest.raises(ValueError):
        edit.set_volume(HB, 128)
    assert edit.set_param(HB, 1, 1, 10).effects[1].params[1] == 10
    assert edit.set_enabled(HB, 0, False).effects[0].enabled is False
    assert HB.effects[0].enabled is True


def test_dsp_percent_sums_catalog_loads():
    expected = sum(CATALOG[i].dsp_load_percent for i in (0x1000080, DLXR, 0x500002A, GEQ, HALL))
    assert edit.dsp_percent(HB, CATALOG) == pytest.approx(expected)


def test_compare_patches_reports_named_field_differences():
    assert edit.compare_patches(edit.sent_form(HB), HB) == []
    other = edit.set_param(HB, 1, 1, 10)
    assert any("param" in d.lower() for d in edit.compare_patches(edit.sent_form(HB), other))
    assert edit.compare_patches(HB, edit.rename(HB, "Other"))
    assert edit.compare_patches(HB, edit.set_volume(HB, 3))
    assert edit.compare_patches(HB, edit.set_enabled(HB, 0, False))
    assert edit.compare_patches(HB, edit.replace_effect(HB, 6, COMP, CATALOG))


def test_write_backup_never_overwrites(tmp_path):
    from zoomstudio.patches.backup import write_backup

    first = write_backup(tmp_path / "autosave", 44, b"one", now="20261124-120000")
    second = write_backup(tmp_path / "autosave", 44, b"two", now="20261124-120000")
    assert first != second and first.read_bytes() == b"one" and second.read_bytes() == b"two"
    assert first.parent == tmp_path / "autosave"
