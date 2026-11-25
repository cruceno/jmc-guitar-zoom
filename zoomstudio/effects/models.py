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
    text = Path(lst_path).read_bytes().decode("utf-8", errors="replace").lstrip()
    doc, _ = json.JSONDecoder().raw_decode(text)
    found: dict[int, PedalModel] = {}
    for model in doc.get("models", []):
        ids = frozenset(int(e["type"], 16) for e in model.get("effects", []))
        if not ids:
            continue
        model_id = int(model["modelId"], 16)
        found[model_id] = PedalModel(model_id, str(model.get("modelName", f"0x{model_id:08X}")), ids)
    return found


def model_id_from_identity(identity) -> int:
    """``0x6E00<member>00`` from an identity reply (``identity.model`` is 0x6E, ``identity.member`` the member)."""
    return (identity.model << 24) | (identity.member << 8)
