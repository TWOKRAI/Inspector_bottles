# -*- coding: utf-8 -*-
"""
ErrorManagerConfig — плоская SchemaBase-схема (только поля + FieldMeta).

Сборка полного dict с severity-каналами — в ``core/error_config_assembly.expand_error_manager_config``.
"""
from __future__ import annotations

from typing import Annotated, Dict, Optional

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("ErrorManagerConfig")
class ErrorManagerConfig(SchemaBase):
    """Конфигурация ErrorManager: пути к файлам и опциональные доп. каналы."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "ErrorManager"
    app_name: Annotated[str, FieldMeta("Имя приложения для логгера")] = "errors"

    critical_file_path: Annotated[str, FieldMeta("Файл критических ошибок")] = "logs/critical.log"
    error_file_path: Annotated[str, FieldMeta("Файл ошибок")] = "logs/errors.log"
    warnings_file_path: Annotated[
        Optional[str],
        FieldMeta("Файл предупреждений (None — не создавать)"),
    ] = "logs/warnings.log"

    default_level: Annotated[str, FieldMeta("Минимальный уровень")] = "WARNING"
    include_stacktrace: Annotated[bool, FieldMeta("Включать stacktrace")] = True
    enable_batching: Annotated[bool, FieldMeta("Батчинг записи")] = True
    batch_size: Annotated[int, FieldMeta("Размер батча", min=1, max=1000)] = 50
    batch_interval: Annotated[float, FieldMeta("Интервал flush, сек", min=0.1, max=60.0)] = 0.5

    channels: Annotated[
        Dict[str, dict],
        FieldMeta("Дополнительные каналы {имя: параметры}"),
    ] = Field(default_factory=dict)
