# -*- coding: utf-8 -*-
"""
Публичные контракты actions_module (единообразие 26/26 модулей framework,
Фаза 2 framework-layer-grouping).

IRegistersManagerGui  — контракт RegistersManager на стороне GUI (set_field_value).
IActionLogWriter      — буферизованный writer персистентного журнала действий.
IActionLogRepository  — CRUD-репозиторий action_log.

IActionLogWriter/IActionLogRepository физически определены в
``persistence/interfaces.py`` (домен персистентности инкапсулирован в
подпакете, реализации живут в Services/sql/action_log/) — здесь канонический
агрегирующий re-export, как в data_schema_module/interfaces.py.
IRegistersManagerGui раньше был объявлен внутри bus.py — поднят сюда как
единая точка контракта; bus.py импортирует его обратно.

Правило: внешние модули импортируют из interfaces.py (или пакетного
__init__.py), не из bus.py/persistence/ напрямую.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .persistence.interfaces import IActionLogRepository, IActionLogWriter

__all__ = [
    "IRegistersManagerGui",
    "IActionLogWriter",
    "IActionLogRepository",
]


@runtime_checkable
class IRegistersManagerGui(Protocol):
    """Протокол для RegistersManager на стороне GUI."""

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> tuple[bool, str | None]:
        """Установить значение поля регистра. Возвращает (ok, error_msg)."""
        ...
