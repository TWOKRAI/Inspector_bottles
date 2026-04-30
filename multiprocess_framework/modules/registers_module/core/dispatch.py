# -*- coding: utf-8 -*-
"""
Доставка register_update: connection_map и разрешение целей dispatch.

См. ADR-RM-003 в ``registers_module/DECISIONS.md``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List


def build_connection_map_from_registers(registers: Dict[str, Any]) -> Dict[str, str]:
    """
    Построить {register_name: process_name} из register_dispatch на классе каждого экземпляра.

    Args:
        registers: Словарь имя → экземпляр регистра (SchemaBase и т.п.).

    Returns:
        Карта для RegistersManager / FrontendRegistersBridge (первый target при нескольких).
    """
    out: Dict[str, str] = {}
    for name, inst in registers.items():
        cls = inst if isinstance(inst, type) else type(inst)
        meta = getattr(cls, "register_dispatch", None)
        if meta is None:
            continue
        targets = getattr(meta, "process_targets", None) or ()
        if not targets:
            continue
        out[name] = targets[0]
    return out


def resolve_dispatch_targets(
    register_name: str,
    field_name: str,
    reg: Any,
    connection_map: Dict[str, str],
    get_field_metadata: Callable[[str, str], Dict[str, Any]],
) -> List[str]:
    """
    Имена процессов для register_update.

    Приоритет: process_targets в FieldMeta.routing → dict из get_field_metadata
    → register_dispatch класса → connection_map.
    """
    get_fm = getattr(type(reg), "get_field_meta", None)
    if callable(get_fm):
        fm = get_fm(field_name)
        if fm is not None and getattr(fm, "routing", None):
            raw_pt = (fm.routing or {}).get("process_targets")
            if raw_pt is not None:
                if isinstance(raw_pt, (list, tuple)) and len(raw_pt) == 0:
                    return []
                if raw_pt:
                    if isinstance(raw_pt, (list, tuple)):
                        return [str(x) for x in raw_pt if x is not None and str(x)]
                    return [str(raw_pt)]

    meta = get_field_metadata(register_name, field_name)
    routing = meta.get("routing") or {}
    raw_pt = routing.get("process_targets")
    if raw_pt is not None:
        if isinstance(raw_pt, (list, tuple)) and len(raw_pt) == 0:
            return []
        if raw_pt:
            if isinstance(raw_pt, (list, tuple)):
                return [str(x) for x in raw_pt if x is not None and str(x)]
            return [str(raw_pt)]

    cls = type(reg)
    dispatch = getattr(cls, "register_dispatch", None)
    if dispatch is not None:
        targets = getattr(dispatch, "process_targets", None) or ()
        if targets:
            return [str(t) for t in targets]

    if register_name in connection_map:
        return [connection_map[register_name]]

    return []
