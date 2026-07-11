"""Фабрика доменных корреляционных буферов DataReceiver (fan-in / join).

C6 шаг (b): выбор `InspectorManager` (region fan-in по count) vs `JoinInspectorManager`
(join именованных входов по seq_id+data_type) — доменное решение (vision-inspection
словарь), переехало из `generic/generic_process.py::_build_inspector` вместе с классами.

Регистрируется в framework-реестре (`process_module.generic.inspector_registry`) при
импорте модуля — generic-движок получает готовый буфер через DI, не зная конкретный класс.
"""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_framework.modules.process_module.generic.inspector_registry import (
    ItemInspector,
    register_inspector_factory,
)

from .inspector_manager import InspectorManager
from .join_inspector_manager import JoinInspectorManager


def build_inspector(
    app_cfg: dict[str, Any],
    log_info: Callable[[str], None] | None = None,
    log_error: Callable[[str], None] | None = None,
    log_debug: Callable[[str], None] | None = None,
) -> ItemInspector:
    """Выбрать корреляционный буфер DataReceiver по конфигу процесса.

    Дефолт `fanin` (InspectorManager, region fan-in по count) — backward-compat.
    `join` (JoinInspectorManager) — generic-слияние именованных входов по
    (seq_id, data_type) для многовходовых узлов (напр. overlay_draw: frame+overlay).

    Конфиг процесса:
        config.inspector.mode: "fanin" | "join"
        config.inspector.inputs: ["frame", "overlay"]      # для join
        config.inspector.primary: "frame"
        config.inspector.timeout_sec / inactive_sec / list_merge_keys
    """
    insp = app_cfg.get("inspector", {}) or {}
    mode = insp.get("mode", "fanin")
    if mode == "join":
        return JoinInspectorManager(
            required_inputs=insp.get("inputs", ["frame", "overlay"]),
            primary=insp.get("primary", "frame"),
            timeout_sec=insp.get("timeout_sec", 0.08),
            list_merge_keys=insp.get("list_merge_keys", ("overlay",)),
            inactive_sec=insp.get("inactive_sec", 1.0),
            log_info=log_info,
            log_error=log_error,
            log_debug=log_debug,
        )
    return InspectorManager(
        timeout_sec=insp.get("timeout_sec", 0.5),
        log_info=log_info,
        log_error=log_error,
        log_debug=log_debug,
    )


# Self-register: импорт этого модуля (через Plugins/__init__) делает фабрику доступной
# generic-движку. Идемпотентно — повторный импорт просто перезапишет тем же значением.
register_inspector_factory(build_inspector)
