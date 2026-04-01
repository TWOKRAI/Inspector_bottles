# -*- coding: utf-8 -*-
"""CommandManagerConfig — плоская схема CommandManager."""
from __future__ import annotations

from typing import Annotated, Literal

from data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("command_manager")
class CommandManagerConfig(SchemaBase):
    """Конфигурация CommandManager (внутренний Dispatcher создаётся отдельно)."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "CommandManager"
    default_strategy: Annotated[
        Literal["exact", "pattern", "fallback", "chain"],
        FieldMeta("Стратегия вложенного Dispatcher"),
    ] = "exact"
    enable_logging: Annotated[bool, FieldMeta("Логирование")] = True
    enable_error_tracking: Annotated[bool, FieldMeta("Трекинг ошибок")] = True
    enable_statistics: Annotated[bool, FieldMeta("Статистика")] = True
