# -*- coding: utf-8 -*-
"""DispatcherConfig — плоская схема Dispatcher."""
from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("dispatcher")
class DispatcherConfig(SchemaBase):
    """Конфигурация универсального Dispatcher."""

    manager_name: Annotated[str, FieldMeta("Имя диспетчера")] = "Dispatcher"
    default_strategy: Annotated[
        Literal["exact", "pattern", "fallback", "chain"],
        FieldMeta("Стратегия по умолчанию"),
    ] = "exact"
    enable_logging: Annotated[bool, FieldMeta("Логирование через Observable")] = True
    enable_error_tracking: Annotated[bool, FieldMeta("Трекинг ошибок")] = True
    enable_statistics: Annotated[bool, FieldMeta("Сбор статистики")] = True
