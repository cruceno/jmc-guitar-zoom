"""Pure editing operations on :class:`Patch` objects (every function returns a new patch).

Slot indexes passed to the operations count the ``0x00000001`` wide fillers, like
``Patch.effects`` does (and like the chain view). Moves, replacements and removals work on
the *logical* chain (fillers removed) and re-insert the fillers afterwards, so a patch edited
here always has the shape the pedal reports.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .model import MAX_EFFECT_SLOTS, NAME_MAX_LEN, PARAM_COUNT, PARAM_MAX, VOLUME_MAX, EffectSlot, Patch

WIDE_FILLER = 0x00000001
DSP_LIMIT_PERCENT = 100.0
NOT_INSTALLED_REASON = "El patch usa efectos que no están en la pedalera"


# ------------------------------------------------------------ chain shape

def logical_slots(patch: Patch) -> list[EffectSlot]:
    """Chain without the wide fillers (real effects and empty slots)."""
    return [s for s in patch.effects if not s.is_wide_filler]


def logical_index(effects: list[EffectSlot], slot_index: int) -> int:
    """Map a slot index (fillers counted) to a position in the logical chain.

    Indexes past the end address the empty tiles the chain view appends after the patch.
    """
    before = sum(1 for s in effects[:slot_index] if not s.is_wide_filler)
    return before + max(0, slot_index - len(effects))


def slot_index_of(patch: Patch, logical: int) -> int:
    """Inverse of :func:`logical_index` for a chain that already contains the fillers."""
    seen = 0
    for i, slot in enumerate(patch.effects):
        if slot.is_wide_filler:
            continue
        if seen == logical:
            return i
        seen += 1
    return len(patch.effects) + (logical - seen)


def _empty() -> EffectSlot:
    return EffectSlot()


def _assemble(patch: Patch, logical: list[EffectSlot], catalog: Mapping[int, Any]) -> Patch:
    """Copy of ``patch`` with ``logical`` as its chain, fillers re-inserted after wide effects."""
    while logical and logical[-1].is_empty:
        logical.pop()
    effects: list[EffectSlot] = []
    for slot in logical:
        effects.append(slot)
        info = catalog.get(slot.effect_id)
        if not slot.is_empty and info is not None and info.is_wide:
            effects.append(EffectSlot(effect_id=WIDE_FILLER))
    if not effects:
        effects.append(_empty())
    out = copy.deepcopy(patch)
    out.effects = effects
    return out


def sent_form(patch: Patch) -> Patch:
    """The patch as it is sent to the pedal: wide fillers removed (the pedal reinserts them)."""
    out = copy.deepcopy(patch)
    out.effects = logical_slots(out) or [_empty()]
    return out


def with_fillers(patch: Patch, catalog: Mapping[int, Any]) -> Patch:
    return _assemble(patch, logical_slots(copy.deepcopy(patch)), catalog)


# ------------------------------------------------------------------ edits

def rename(patch: Patch, name: str) -> Patch:
    out = copy.deepcopy(patch)
    out.name = name
    if len(name) > NAME_MAX_LEN or not all(32 <= ord(c) < 127 for c in name):
        raise ValueError(f"el nombre admite hasta {NAME_MAX_LEN} caracteres ASCII imprimibles")
    return out


def set_volume(patch: Patch, volume: int) -> Patch:
    if not 0 <= volume <= VOLUME_MAX:
        raise ValueError(f"el volumen debe estar entre 0 y {VOLUME_MAX}")
    out = copy.deepcopy(patch)
    out.volume = volume
    return out


def set_param(patch: Patch, slot_index: int, index: int, value: int) -> Patch:
    if not 0 <= index < PARAM_COUNT or not 0 <= value <= PARAM_MAX[index]:
        raise ValueError(f"el parámetro {index} debe estar entre 0 y {PARAM_MAX[index] if 0 <= index < PARAM_COUNT else '?'}")
    out = copy.deepcopy(patch)
    out.effects[slot_index].params[index] = value
    return out


def set_enabled(patch: Patch, slot_index: int, enabled: bool) -> Patch:
    out = copy.deepcopy(patch)
    out.effects[slot_index].enabled = enabled
    return out


def default_params(info: Any) -> list[int]:
    """Catalog defaults for a new effect: the real parameters, then the ``Dummy`` records.

    ``EffectInfo.params`` leaves the dummies out, so their defaults are read again from the
    ZD2 file (they are 0 in every effect checked so far); a failure falls back to 0.
    """
    params = [0] * PARAM_COUNT
    for i, p in enumerate(info.params[:PARAM_COUNT]):
        params[i] = p.default
    path = getattr(info, "path", None)
    if getattr(info, "dummy_count", 0) and path is not None:
        try:
            import zoomzt2

            from zoomstudio.effects.catalog import _parse_records

            zd2 = zoomzt2.ZD2.parse_file(str(path))
            table = _parse_records(zd2.DATA.data)[2:]
            for i, (_name, _max, default) in enumerate(table[:PARAM_COUNT]):
                if i >= len(info.params):
                    params[i] = default
        except Exception:  # unreadable file: dummies stay 0
            pass
    return [min(v, PARAM_MAX[i]) for i, v in enumerate(params)]


def new_slot(info: Any) -> EffectSlot:
    return EffectSlot(effect_id=info.effect_id, enabled=True, params=default_params(info))


def _pad(logical: list[EffectSlot], length: int) -> None:
    while len(logical) < length:
        logical.append(_empty())


def replace_effect(patch: Patch, slot_index: int, effect_id: int, catalog: Mapping[int, Any]) -> Patch:
    info = catalog.get(effect_id)
    if info is None:
        raise ValueError(f"el efecto 0x{effect_id:08X} no está en el catálogo")
    logical = copy.deepcopy(logical_slots(patch))
    pos = logical_index(patch.effects, slot_index)
    _pad(logical, pos + 1)
    logical[pos] = new_slot(info)
    return _assemble(patch, logical, catalog)


def remove_effect(patch: Patch, slot_index: int, catalog: Mapping[int, Any]) -> Patch:
    logical = copy.deepcopy(logical_slots(patch))
    pos = logical_index(patch.effects, slot_index)
    if pos < len(logical):
        logical[pos] = _empty()
    return _assemble(patch, logical, catalog)


def move_effect(patch: Patch, from_slot: int, to_slot: int, catalog: Mapping[int, Any]) -> Patch:
    logical = copy.deepcopy(logical_slots(patch))
    src = logical_index(patch.effects, from_slot)
    dst = logical_index(patch.effects, to_slot)
    if src >= len(logical):
        raise ValueError("no hay nada que mover")
    _pad(logical, dst + 1)
    logical.insert(dst, logical.pop(src))
    return _assemble(patch, logical, catalog)


# ----------------------------------------------------------- measurements

def dsp_percent(patch: Patch, catalog: Mapping[int, Any]) -> float:
    """Sum of the catalog DSP load of every effect of the chain (enabled or not)."""
    total = 0.0
    for slot in patch.effects:
        info = catalog.get(slot.effect_id)
        if info is not None and not slot.is_placeholder:
            total += info.dsp_load_percent
    return total


def _comparable(patch: Patch) -> tuple:
    chain = logical_slots(patch)
    while chain and chain[-1].is_empty:
        chain.pop()
    slots = [(s.effect_id, None, None) if s.is_empty else (s.effect_id, s.enabled, tuple(s.params))
             for s in chain]
    return patch.name, patch.volume, slots


def compare_patches(sent: Patch, got: Patch) -> list[str]:
    """Differences in name, volume, effect IDs, enabled flags and params (fillers and trailing
    empty slots ignored); an empty list means the read-back matches what was sent."""
    (n1, v1, s1), (n2, v2, s2) = _comparable(sent), _comparable(got)
    diffs: list[str] = []
    if n1 != n2:
        diffs.append(f"nombre {n1!r} != {n2!r}")
    if v1 != v2:
        diffs.append(f"volumen {v1} != {v2}")
    if [s[0] for s in s1] != [s[0] for s in s2]:
        diffs.append("efectos " + ",".join(f"{s[0]:08X}" for s in s1) + " != "
                     + ",".join(f"{s[0]:08X}" for s in s2))
        return diffs
    for i, (a, b) in enumerate(zip(s1, s2)):
        if a[1] != b[1]:
            diffs.append(f"efecto {i}: encendido {a[1]} != {b[1]}")
        if a[2] != b[2]:
            changed = [f"parámetro{k + 1} {x} != {y}" for k, (x, y) in enumerate(zip(a[2] or (), b[2] or ())) if x != y]
            diffs.append(f"efecto {i}: " + ", ".join(changed))
    return diffs


# ------------------------------------------------------- save eligibility

UNKNOWN_EFFECT_REASON = "efecto desconocido: no se puede comprobar la carga de DSP"
NOT_RUNNABLE_REASON = "no funciona en la A1 FOUR"


def slot_problems(patch: Patch, catalog: Mapping[int, Any], allowed_ids: set[int] | None) -> dict[int, str]:
    """Reason per chain slot index (fillers counted) that blocks writing the patch to the pedal.

    An effect missing from the catalog cannot be measured (A2); one outside ``allowed_ids`` (the set
    the catalog filter offers) is not runnable on the A1 FOUR (A1). ``allowed_ids=None`` means no
    restriction.
    """
    out: dict[int, str] = {}
    for i, slot in enumerate(patch.effects):
        if slot.is_placeholder:
            continue
        if slot.effect_id not in catalog:
            out[i] = UNKNOWN_EFFECT_REASON
        elif allowed_ids is not None and slot.effect_id not in allowed_ids:
            out[i] = NOT_RUNNABLE_REASON
    return out


def not_installed_slots(patch: Patch, catalog: Mapping[int, Any], installed_ids: set[int] | None) -> list[int]:
    """Slot indexes (fillers counted) whose effect is known not to be installed on the connected pedal.

    ``installed_ids=None`` means the pedal's effect list is not known (offline, not read yet): nothing is guessed,
    so no slot is reported. An effect the catalog does not know is reported by ``slot_problems`` instead.
    """
    if installed_ids is None:
        return []
    return [i for i, slot in enumerate(patch.effects)
            if not slot.is_placeholder and slot.effect_id in catalog and slot.effect_id not in installed_ids]


def not_installed_names(patch: Patch, catalog: Mapping[int, Any], installed_ids: set[int] | None) -> list[str]:
    """Names of the effects of ``not_installed_slots``, each once, in chain order."""
    return list(dict.fromkeys(catalog[patch.effects[i].effect_id].name
                              for i in not_installed_slots(patch, catalog, installed_ids)))


def save_blockers(patch: Patch, catalog: Mapping[int, Any], allowed_ids: set[int] | None,
                  installed_ids: set[int] | None = None) -> list[str]:
    """Every reason the patch must not be written to the pedal (empty list: it may be written).

    ``installed_ids``: the effects installed on the connected pedal; ``None`` (the default) leaves that check out.
    """
    reasons: list[str] = []
    for i, why in slot_problems(patch, catalog, allowed_ids).items():
        info = catalog.get(patch.effects[i].effect_id)
        reasons.append(f"{info.name if info else '0x%08X' % patch.effects[i].effect_id}: {why}")
    missing = not_installed_names(patch, catalog, installed_ids)
    if missing:
        reasons.append(f"{NOT_INSTALLED_REASON}: {', '.join(missing)}")
    dsp = dsp_percent(patch, catalog)
    if dsp > DSP_LIMIT_PERCENT + 1e-9:
        reasons.append(f"la carga de DSP es {dsp:.0f} %: debe ser 100 % o menos para guardar")
    try:
        chain = len(with_fillers(patch, catalog).effects)
    except Exception:  # a malformed chain is reported by the other checks
        chain = len(patch.effects)
    if chain > MAX_EFFECT_SLOTS:
        reasons.append(f"la cadena necesita {chain} slots con los rellenos de los efectos anchos; el máximo es "
                       f"{MAX_EFFECT_SLOTS}")
    return reasons
