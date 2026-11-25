"""Spanish texts for effect and parameter descriptions.

The pedal's ``.zd2`` files carry English text only. ``descriptions_es.json``
holds two maps:

* ``effects``: extended Spanish description keyed by effect ID (``"0x01000010"``);
* ``texts``: Spanish translation keyed by the exact English text (stripped).

Lookups fall back to the English original when nothing is found.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jmc_guitar_zoom.effects.catalog import EffectInfo, ParamInfo

_DATA_FILE = Path(__file__).with_name("descriptions_es.json")


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, str]]:
    data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return {"effects": data.get("effects", {}), "texts": data.get("texts", {})}


def to_spanish(text: str) -> str:
    """Translation of ``text.strip()``, or ``text`` unchanged when there is none."""
    if not text:
        return text
    return _load()["texts"].get(text.strip(), text)


def effect_description(info: EffectInfo) -> str:
    """Extended description by effect ID, else translated, else the English one."""
    extended = _load()["effects"].get("0x%08x" % info.effect_id)
    return extended if extended else to_spanish(info.description)


def param_explanation(param: ParamInfo) -> str:
    return to_spanish(param.explanation)
