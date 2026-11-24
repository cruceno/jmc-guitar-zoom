import copy
import struct
from pathlib import Path

import pytest

import decode_preset as d
from zoomstudio.patches.model import EffectSlot
from zoomstudio.patches.zptc import PATCH_BUFFER_SIZE, build_zptc, parse_zptc

FIX = Path(__file__).parent / "fixtures"
FIXTURES = ["001.zptc", "019.zptc", "041.zptc", "53-HB-Jazz.zptc"]


def raw(name):
    return (FIX / name).read_bytes()


def logical_len(data):
    # The ZPTC length field counts the whole logical file (verified on all 50 backups).
    return struct.unpack("<I", data[4:8])[0]


@pytest.mark.parametrize("name", FIXTURES)
def test_round_trip_is_lossless(name):
    data = raw(name)
    out = build_zptc(parse_zptc(data))
    n = logical_len(data)
    assert len(out) == PATCH_BUFFER_SIZE == 760
    assert out[:n] == data[:n]
    assert out[n:] == b"\x00" * (760 - n)


def test_parsed_values_match_decode_preset():
    data = raw("001.zptc")
    cfg = d.ZPTC.parse(data)
    patch = parse_zptc(data)
    assert patch.name == "AG D-28"
    assert patch.volume == 100
    assert [s.effect_id for s in patch.effects] == [int(i) for i in cfg.ids]
    assert patch.effects[0].effect_id == 0x14400000
    for slot, fx in zip(patch.effects, cfg.EDTB.effects):
        bw = fx.reversed.bitwise
        assert slot.enabled == bool(bw.enabled)
        assert slot.params == [bw["param%d" % n] for n in range(1, 13)]


def test_placeholders_are_exposed_and_kept():
    patch = parse_zptc(raw("53-HB-Jazz.zptc"))
    assert [s.is_placeholder for s in patch.effects] == [False, False, True, False, False, True, False]
    assert patch.effects[2].is_wide_filler and not patch.effects[2].is_empty
    empty = parse_zptc(raw("041.zptc"))
    assert all(s.is_empty and s.is_placeholder for s in empty.effects)


def test_edits_round_trip():
    patch = parse_zptc(raw("001.zptc"))
    patch.name = "My Patch"
    patch.volume = 77
    patch.effects[1].params[0] = 1234
    patch.effects[1].params[6] = 200  # 8-bit field
    patch.description = "Edited description"
    again = parse_zptc(build_zptc(patch))
    assert again.name == "My Patch"
    assert again.volume == 77
    assert again.effects[1].params[0] == 1234
    assert again.effects[1].params[6] == 200
    assert again.description == "Edited description"
    assert [s.effect_id for s in again.effects] == [s.effect_id for s in patch.effects]
    # re-parse of the rebuilt buffer is stable
    assert build_zptc(again) == build_zptc(patch)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: setattr(p, "name", "ELEVENCHARS"),
        lambda p: setattr(p, "name", "Ñandú"),
        lambda p: setattr(p, "volume", 128),
        lambda p: p.effects[0].params.__setitem__(0, 4096),
        lambda p: p.effects[0].params.__setitem__(5, 256),
        lambda p: p.effects[0].params.__setitem__(0, -1),
        lambda p: setattr(p.effects[0], "params", [0] * 11),
        lambda p: setattr(p, "effects", []),
    ],
)
def test_invalid_values_raise(mutate):
    patch = parse_zptc(raw("001.zptc"))
    mutate(patch)
    with pytest.raises(ValueError):
        build_zptc(patch)


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_zptc(b"not a patch")


def test_build_does_not_mutate_input():
    patch = parse_zptc(raw("001.zptc"))
    snapshot = copy.deepcopy(patch)
    build_zptc(patch)
    assert patch == snapshot


def test_rebuild_019_with_hbjazz_chain_matches_sent_file():
    sent = parse_zptc(raw("53-HB-Jazz.sent.zptc"))
    patch = parse_zptc(raw("019.zptc"))
    assert len(patch.effects) == len(sent.effects) == 5
    chain = [
        (0x01000080, [4, 55, 42, 62]),
        (0x0400002C, [0, 42, 28, 38, 75, 0, 40, 0, 0]),
        (0x0500002A, [0, 70, 35, 55]),
        (0x02000054, [23, 25, 26, 24, 23, 20, 19, 80, 0]),
        (0x09000030, [20, 11, 24, 1]),
    ]
    patch.name = "HB Jazz"
    patch.description = sent.description
    for slot, (fx, params) in zip(patch.effects, chain):
        slot.effect_id = fx
        slot.enabled = True
        slot.params = params + [0] * (12 - len(params))
    out = parse_zptc(build_zptc(patch))
    assert out.name == sent.name
    assert out.volume == sent.volume == 100
    assert out.description == sent.description
    assert [(s.effect_id, s.enabled, s.params) for s in out.effects] == [
        (s.effect_id, s.enabled, s.params) for s in sent.effects
    ]


@pytest.mark.parametrize("text", ["", "abcd", "abcde", "x" * 44, "x" * 45])
def test_description_lengths_round_trip(text):
    patch = parse_zptc(raw("001.zptc"))
    patch.description = text
    out = build_zptc(patch)
    assert parse_zptc(out).description == text
    assert struct.unpack("<I", out[4:8])[0] <= 760
