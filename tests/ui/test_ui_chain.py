import pytest
from PySide6.QtCore import QPoint

from ui_replies import FIXTURES
from jmc_guitar_zoom.effects.catalog import load_catalog
from jmc_guitar_zoom.ui import strings, tokens
from jmc_guitar_zoom.ui.chain import FOOT, PEDAL_MIN_W, ChainView
from jmc_guitar_zoom.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot):
    w = MainWindow(load_catalog(("pedal", FIXTURES / "catalog")), a1_ids={0x1000010})
    qtbot.addWidget(w)
    w.load_offline(FIXTURES / "backup")
    w.show()
    w.select_location(44)  # HB Jazz: five effects, two of them wide
    return w


def test_every_pedal_has_the_same_size_and_they_are_evenly_spread(window):
    tiles = window.chain_tiles()
    assert len({(t.width(), t.height()) for t in tiles}) == 1
    gaps = {tiles[i + 1].x() - tiles[i].x() for i in range(len(tiles) - 1)}
    assert max(gaps) - min(gaps) <= 1
    assert [t.span for t in tiles if not t.is_empty] == [1, 2, 1, 2, 1]  # wide effects keep their span only


def test_wide_effects_get_a_badge_not_a_bigger_pedal(window):
    real = [t for t in window.chain_tiles() if not t.is_empty]
    assert [t.body.badge_text() for t in real] == ["", strings.BADGE_TWO_SLOTS, "", strings.BADGE_TWO_SLOTS, ""]
    assert real[1].size() == real[0].size()


def test_footswitch_is_round_sized_40_and_outside_the_pedal_body(window):
    tile = window.chain_tiles()[0]
    assert tile.power.parentWidget() is tile and tile.power.size().width() == tile.power.size().height() == FOOT
    assert tile.power.geometry().top() >= tile.body.geometry().bottom()


def test_footswitch_name_is_the_action_and_it_toggles_the_effect(window):
    tile = window.chain_tiles()[0]
    assert tile.power.accessibleName() == f"{strings.TURN_OFF} {tile.effect_name}"
    tile.power.click()
    assert tile.power.accessibleName() == f"{strings.TURN_ON} {tile.effect_name}"
    assert window.current_patch.effects[0].enabled is False and not tile.is_enabled_effect


def test_empty_slots_are_dashed_pedals_without_a_footswitch(window):
    window.remove_effect(6)
    empty = [t for t in window.chain_tiles() if t.is_empty]
    assert empty and all(t.power.isHidden() and t.remove_button.isHidden() for t in empty)
    assert empty[0].size() == window.chain_tiles()[0].size()


def test_pedal_that_cannot_be_written_is_flagged(window):
    flagged = [t for t in window.chain_tiles() if t.problem]
    assert flagged and strings.tile_problem_tip(flagged[0].problem) in flagged[0].toolTip()


def test_remove_button_asks_to_remove_that_slot(window, qtbot):
    tile = window.chain_tiles()[1]
    with qtbot.waitSignal(window.chain.remove_requested) as blocker:
        tile.remove_button.click()
    assert blocker.args == [tile.slot_index]


def test_pedals_never_shrink_below_the_minimum_width(qtbot):
    chain = ChainView()
    qtbot.addWidget(chain)
    chain.resize(300, chain.height())
    assert chain.pedal_width() == PEDAL_MIN_W and chain.minimumSizeHint().width() > 300


def test_selected_pedal_is_painted_with_a_ring(window):
    tile = window.chain_tiles()[0]
    window.select_tile(tile.slot_index)
    image = tile.body.grab().toImage()
    ring = tokens.color("text-primary")
    assert any(image.pixelColor(x, y).rgb() == ring.rgb() for x in range(0, 60) for y in range(0, 12))
