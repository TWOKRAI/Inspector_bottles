# -*- coding: utf-8 -*-
"""
Сборка connection_map из метаданных регистров (RegisterDispatchMeta).

Используется приложением как единый источник: не дублировать dict вручную.
Для fan-out в карту попадает только первый процесс (совместимость Dict[str, str]);
полный список целей читает RegistersManager из register_dispatch при set_field_value.
"""
from __future__ import annotations

from typing import Any, Dict


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
