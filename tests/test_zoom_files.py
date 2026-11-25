"""Checks against Zoom's real files, fetched by ``scripts/fetch_test_fixtures.py`` (skipped without them).

They keep the synthetic fixtures honest: the effects the factories imitate must still look the way Zoom's own
files look to the catalog, and the channel's list must still parse with the app's readers.
"""
import pytest

import zd2_factory as zf
from fixture_files import ZOOM_FILES
from jmc_guitar_zoom.effects.catalog import a1four_effect_ids, load_catalog, load_zd2
from jmc_guitar_zoom.effects.models import A1_FOUR, load_models

pytestmark = pytest.mark.zoom_files
FOLDER = ZOOM_FILES / "effects"
LST = FOLDER / "AllZDL7_2.lst"


def test_the_channel_list_parses_and_has_the_a1_four():
    models = load_models(LST)
    assert models[A1_FOUR].name == "A1 FOUR"
    assert models[A1_FOUR].effect_ids == a1four_effect_ids(LST) and models[A1_FOUR].effect_ids


def test_every_fetched_effect_loads_with_parameters_and_an_id_the_list_knows():
    catalog = load_catalog(FOLDER)
    assert catalog
    known = set().union(*(m.effect_ids for m in load_models(LST).values()))
    for info in catalog.values():
        assert info.effect_id in known, info.filename
        assert info.name and info.group and info.params, info.filename
        assert all(p.max >= 0 and 0 <= p.default for p in info.params), info.filename


def test_the_synthetic_effects_match_the_real_ones_that_were_fetched(tmp_path):
    # name, group and the parameter names and ranges are what patches and the editor depend on
    shape = lambda i: (i.name, i.group, [(p.name, p.max) for p in i.params], i.is_wide)  # noqa: E731
    checked = 0
    for real in load_catalog(FOLDER).values():
        for fx in zf.EFFECTS.values():
            if fx.effect_id == real.effect_id:
                path = tmp_path / "x.zd2"
                path.write_bytes(zf.build_zd2(fx))
                assert shape(load_zd2(path)) == shape(real), fx.name
                checked += 1
    assert checked
