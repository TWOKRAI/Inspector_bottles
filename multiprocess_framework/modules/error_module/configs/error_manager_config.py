# -*- coding: utf-8 -*-
"""
ErrorManagerConfig — плоская SchemaBase-схема (только поля + FieldMeta).

Сборка полного dict с severity-каналами — в ``core/error_config_assembly.expand_error_manager_config``.
"""

from __future__ import annotations

from typing import Annotated, Dict, Optional

from pydantic import Field, field_validator

from multiprocess_framework.modules.channel_routing_module.buffers.batch_buffer import (
    DEFAULT_MAX_PENDING,
    DEFAULT_OVERFLOW_POLICY,
    validate_overflow_policy,
)
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
    batch_max_pending: Annotated[
        int,
        FieldMeta("Потолок неотправленных записей на канал (0 — без потолка)", min=0, max=1_000_000),
    ] = DEFAULT_MAX_PENDING
    batch_overflow_policy: Annotated[
        str,
        FieldMeta("Что терять при переполнении: drop_oldest | drop_newest"),
    ] = DEFAULT_OVERFLOW_POLICY

    channels: Annotated[
        Dict[str, dict],
        FieldMeta("Дополнительные каналы {имя: параметры}"),
    ] = Field(default_factory=dict)

    @field_validator("batch_overflow_policy")
    @classmethod
    def _check_overflow_policy(cls, value: str) -> str:
        """Отказ на границе конфига — до того, как правка коснётся менеджеров."""
        return validate_overflow_policy(value)
