"""The editor catalog shows only what the target pedal can run; the target follows the connected pedal."""
from types import SimpleNamespace

import pytest

from ui_replies import FIXTURES
from zoomstudio.effects import models as pedal_models
from zoomstudio.effects.catalog import load_catalog
from zoomstudio.effects.models import A1_FOUR, load_models
from zoomstudio.ui import strings as ST
from zoomstudio.ui.cards import ROLE_EFFECT
from zoomstudio.ui.main_window import MainWindow
from zoomstudio.ui.settings import TargetStore

G5N = 0x6E000000
LST = FIXTURES / "AllZDL7_2.lst"
A1_NAMES = {"Comp", "FD DLXR", "Gt GEQ 7", "Hall"}  # the fixture catalog's effects Guitar Lab lists for the A1 FOUR


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(("pedal", FIXTURES / "catalog"))


@pytest.fixture(scope="module")
def registry():
    return load_models(LST)


def make(qtbot, catalog, registry, tmp_path, **kw):
    w = MainWindow(catalog, models=registry, bank_dir=tmp_path / "bank", **kw)
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    return w


def effect_items(panel):
    return [panel.list.item(i) for i in range(panel.list.count()) if panel.list.item(i).data(ROLE_EFFECT)]


def test_the_catalog_shows_only_effects_compatible_with_the_target_and_says_how_many(qtbot, catalog, registry, tmp_path):
    w = make(qtbot, catalog, registry, tmp_path)
    panel = w.catalog_panel
    assert w.target_model == A1_FOUR
    assert set(panel.visible_names()) == A1_NAMES
    assert panel.count_label.text() == ST.compatible_count(4, "A1 FOUR") == "4 compatibles con A1 FOUR"
    assert w.allowed_ids == set(registry[A1_FOUR].effect_ids)


def test_there_is_no_a1_checkbox_and_no_not_a1_badge(qtbot, catalog, registry, tmp_path):
    w = make(qtbot, catalog, registry, tmp_path)
    panel = w.catalog_panel
    assert not hasattr(panel, "a1_check") and not hasattr(ST, "ONLY_A1") and not hasattr(ST, "BADGE_NOT_A1")
    assert all("blocked" not in item.data(ROLE_EFFECT) for item in effect_items(panel))


def test_the_target_follows_the_connected_pedal_when_it_is_supported(qtbot, catalog, registry, tmp_path, monkeypatch):
    monkeypatch.setattr(pedal_models, "SUPPORTED_MODELS", {A1_FOUR, G5N})
    w = make(qtbot, catalog, registry, tmp_path)
    assert w.target_model == A1_FOUR
    w.apply_pedal_identity(SimpleNamespace(model=0x6E, member=0x00))  # a G5n
    assert w.connected_model == G5N and w.target_model == G5N
    assert w.catalog_panel.pedal_combo.currentData() == G5N
    w.apply_pedal_identity(SimpleNamespace(model=0x6E, member=0x0C))  # G1 FOUR: known, not supported
    assert w.connected_model == 0x6E000C00 and w.target_model == G5N  # the target stays


def test_offline_the_target_is_the_last_one_used_then_the_a1_four(qtbot, catalog, registry, tmp_path, monkeypatch):
    monkeypatch.setattr(pedal_models, "SUPPORTED_MODELS", {A1_FOUR, G5N})
    store = TargetStore(tmp_path / "target.json")
    assert make(qtbot, catalog, registry, tmp_path, target_store=store).target_model == A1_FOUR
    store.set_target(G5N)
    assert make(qtbot, catalog, registry, tmp_path, target_store=TargetStore(tmp_path / "target.json")).target_model == G5N
    store.set_target(0x6E000C00)  # a stored target that is no longer supported falls back
    assert make(qtbot, catalog, registry, tmp_path, target_store=TargetStore(tmp_path / "target.json")).target_model == A1_FOUR


def test_the_selector_is_hidden_with_one_supported_pedal_and_shown_with_two(qtbot, catalog, registry, tmp_path, monkeypatch):
    w = make(qtbot, catalog, registry, tmp_path)
    w.show()
    assert not w.catalog_panel.pedal_combo.isVisibleTo(w)
    monkeypatch.setattr(pedal_models, "SUPPORTED_MODELS", {A1_FOUR, G5N})
    w2 = make(qtbot, catalog, registry, tmp_path)
    w2.show()
    combo = w2.catalog_panel.pedal_combo
    assert combo.isVisibleTo(w2) and combo.count() == 2
    assert [combo.itemText(i) for i in range(2)] == ["A1 FOUR", "G5n"] or {combo.itemText(i) for i in range(2)} == {"A1 FOUR", "G5n"}
    assert combo.currentData() == A1_FOUR  # preselected: the target


def test_choosing_a_pedal_refilters_and_remembers_it(qtbot, catalog, registry, tmp_path, monkeypatch):
    monkeypatch.setattr(pedal_models, "SUPPORTED_MODELS", {A1_FOUR, G5N})
    store = TargetStore(tmp_path / "target.json")
    w = make(qtbot, catalog, registry, tmp_path, target_store=store)
    panel = w.catalog_panel
    before = set(panel.visible_names())
    panel.pedal_combo.setCurrentIndex(panel.pedal_combo.findData(G5N))
    expected = {i.name for i in catalog.values() if i.effect_id in registry[G5N].effect_ids}
    assert w.target_model == G5N and set(panel.visible_names()) == expected and expected != before
    assert panel.count_label.text() == ST.compatible_count(len(expected), "G5n")
    assert TargetStore(tmp_path / "target.json").target == G5N
