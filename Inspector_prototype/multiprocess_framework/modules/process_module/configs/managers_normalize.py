# -*- coding: utf-8 -*-
"""
Единая нормализация секций менеджеров из dict конфига процесса / proc_dict.

Согласовано с ProcessManagers.initialize: ключи logger, error, stats,
router, command, console.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet

# Секции, которые читает ProcessManagers (и ManagersConfig.model_dump).
MANAGER_SECTION_KEYS: FrozenSet[str] = frozenset(
    {"logger", "error", "stats", "router", "command", "console"}
)


def _collect_flat_sections(d: Dict[str, Any]) -> Dict[str, Any]:
    """Собрать только известные секции из одного уровня dict."""
    out: Dict[str, Any] = {}
    for k in MANAGER_SECTION_KEYS:
        v = d.get(k)
        if isinstance(v, dict) and v:
            out[k] = v
    return out


def normalize_managers_view(process_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Вернуть словарь секций менеджеров для ProcessManagers.

    Порядок приоритета:
    1. Непустой ``process_config["managers"]`` (legacy / top-level в proc_dict).
    2. Непустой ``process_config["config"]["managers"]`` (канон SchemaBase + build()).
    3. Плоские секции внутри ``process_config["config"]`` без обёртки ``managers``.
    4. Плоские секции на верхнем уровне ``process_config`` (минимальные dict без ключа managers).
    """
    if not isinstance(process_config, dict):
        return {}

    m = process_config.get("managers")
    if isinstance(m, dict) and m:
        return dict(m)

    cfg = process_config.get("config")
    if isinstance(cfg, dict):
        m2 = cfg.get("managers")
        if isinstance(m2, dict) and m2:
            return dict(m2)
        flat = _collect_flat_sections(cfg)
        if flat:
            return flat

    return _collect_flat_sections(process_config)
