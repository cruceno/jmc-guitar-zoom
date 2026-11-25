"""Pedal models Guitar Lab knows (``AllZDL7_2.lst``) and which of them this app can edit.

No Qt here. The list is JSON followed by garbage, so it is read with ``raw_decode``. A model id is
``0x6E00<member>00``: the member byte is the one the pedal reports in its identity reply (the A1 FOUR is
member 0x11, id ``0x6E001100``). The app's protocol is verified only on the A1 FOUR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

A1_FOUR = 0x6E001100
SUPPORTED_MODELS: set[int] = {A1_FOUR}  # the pedals the app can edit today


@dataclass(frozen=True)
class PedalModel:
    model_id: int
    name: str
    effect_ids: frozenset[int]


def load_models(lst_path: str | Path) -> dict[int, PedalModel]:
    """Every model of the list that has effects (entries without any, such as the demo ones, are left out)."""
    return parse_models(Path(lst_path).read_bytes())


def parse_models(raw: bytes) -> dict[int, PedalModel]:
    """Models from the list's bytes (JSON plus trailing garbage).

    The list comes from the network, so an unusable entry (not an object, a bad hex id, no effects array)
    is skipped instead of failing the whole list; a document that is not JSON still raises ValueError.
    """
    doc, _ = json.JSONDecoder().raw_decode(raw.decode("utf-8", errors="replace").lstrip())
    models = doc.get("models") if isinstance(doc, dict) else None
    found: dict[int, PedalModel] = {}
    for model in models if isinstance(models, list) else []:
        if not isinstance(model, dict):
            continue
        model_id = _hex(model.get("modelId"))
        effects = model.get("effects")
        if model_id is None or not isinstance(effects, list):
            continue
        ids = frozenset(i for i in (_hex(e.get("type")) for e in effects if isinstance(e, dict)) if i is not None)
        if ids:
            found[model_id] = PedalModel(model_id, str(model.get("modelName") or f"0x{model_id:08X}"), ids)
    return found


def _hex(value) -> int | None:
    try:
        return int(value, 16) if isinstance(value, str) else None
    except ValueError:
        return None


def model_id_from_identity(identity) -> int:
    """``0x6E00<member>00`` from an identity reply (``identity.model`` is 0x6E, ``identity.member`` the member)."""
    return (identity.model << 24) | (identity.member << 8)
