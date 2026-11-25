"""A synthetic ``AllZDL7_2.lst``: Guitar Lab's effect list, reduced to the two models the tests use.

The real list is JSON followed by garbage (the app reads it with ``raw_decode``). Shape, per model::

    {"modelId": "0x6E001100", "modelName": "A1 FOUR", "editor": true, "patch": true,
     "effects": [{"type": "0x01000010", "fileName": "COMP.zip", "version": "1.40"}, ...]}

``type`` is the effect id (sometimes zero padded, sometimes not: both forms are written here), ``fileName`` the zip
on Zoom's channel and ``version`` its version. The A1 FOUR holds seven effects; the G5n holds more, including ids
only it has. ``zdl_url`` is the channel's base URL.
"""
from __future__ import annotations

import json

TRAILER = b"\n   \n\x00"  # what follows the JSON in the real file


def _effect(effect_type: str, file_name: str, version: str) -> dict:
    return {"type": effect_type, "fileName": file_name, "version": version}


A1_EFFECTS = [
    _effect("0x8000021", "ANDLY_3S.zip", "1.10"), _effect("0x2000010", "AUTOWAH.zip", "1.40"),
    _effect("0x02800010", "B_ATWAH.zip", "1.40"), _effect("0x1000010", "COMP.zip", "1.40"),
    _effect("0x0400002C", "FDDLXR1U.zip", "1.10"), _effect("0x02000054", "GTGEQ71U.zip", "1.20"),
    _effect("0x9000030", "HALL.zip", "1.50"),
]
G5N_EXTRA = [
    _effect("0x04080021", "REDLM_GN.zip", "1.00"), _effect("0x05080020", "RED4X10.zip", "1.00"),
    _effect("0x1000080", "OPTCOMP.zip", "1.50"), _effect("0x1000020", "RACKCOMP.zip", "1.40"),
    _effect("0x500002A", "FDDX1X12.zip", "1.40"), _effect("0x1800030", "160_COMP.zip", "1.40"),
    _effect("0x14400190", "MDL_12ST.zip", "1.00"),
]


def build_lst() -> bytes:
    doc = {"zdl_url": "https://www.zoom.co.jp/archive/GUITAR_LAB/ZDLF3/", "models": [
        {"modelId": "0x6E000000", "modelName": "G5n", "editor": True, "patch": True,
         "effects": A1_EFFECTS + G5N_EXTRA},
        {"modelId": "0x6E001100", "modelName": "A1 FOUR", "editor": True, "patch": True, "effects": A1_EFFECTS},
    ]}
    return json.dumps(doc, indent=1).encode() + TRAILER
