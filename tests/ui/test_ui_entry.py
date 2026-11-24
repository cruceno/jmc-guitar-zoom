from pathlib import Path

from zoomstudio.__main__ import autosave_dir, offerable_effect_ids
from zoomstudio.effects.catalog import EffectInfo


def info(effect_id, sources):
    return EffectInfo(effect_id, "x.zd2", "x", "g", "1.0", 1.0, "", sources=sources)


def test_offerable_ids_add_pedal_effects_missing_from_the_a1_list():
    catalog = {1: info(1, ["pedal"]), 2: info(2, ["Guitar Lab"]), 3: info(3, ["Guitar Lab"])}
    assert offerable_effect_ids(catalog, {3}) == {1, 3}
    assert offerable_effect_ids(catalog, None) is None


def test_autosave_dir_is_next_to_the_repo():
    assert autosave_dir(Path("/w")) == Path("/w/patches/autosave")
