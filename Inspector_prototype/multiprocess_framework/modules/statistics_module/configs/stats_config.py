# -*- coding: utf-8 -*-
"""
StatsManagerConfig — конфигурация менеджера статистики.

Наследует ChannelRoutingConfig, добавляет параметры агрегации, flush,
логирования метрик и тегов по умолчанию.
"""
from typing import Annotated, Dict

from ...channel_routing_module.core.config import ChannelRoutingConfig
from ...data_schema_module import FieldMeta, register_schema


@register_schema("StatsManagerConfig")
class StatsManagerConfig(ChannelRoutingConfig):
    """Конфигурация StatsManager.

    Поля:
        manager_name         — имя менеджера
        channels             — каналы вывода (log, file, ...)
        aggregation_interval — интервал агрегации метрик, сек
        flush_interval       — интервал flush в каналы, сек
        enable_logging       — логировать метрики через LoggerManager
        log_level            — уровень логирования метрик
        default_tags         — теги по умолчанию для всех метрик
        retention_seconds     — время хранения метрик в памяти, сек
    """

    manager_name: Annotated[
        str,
        FieldMeta("Имя менеджера статистики"),
    ] = "StatsManager"

    aggregation_interval: Annotated[
        float,
        FieldMeta("Интервал агрегации, сек", min=0.1, max=60.0),
    ] = 5.0

    flush_interval: Annotated[
        float,
        FieldMeta("Интервал flush в каналы, сек", min=1.0, max=300.0),
    ] = 10.0

    enable_logging: Annotated[
        bool,
        FieldMeta("Логировать метрики через LoggerManager"),
    ] = True

    log_level: Annotated[
        str,
        FieldMeta("Уровень логирования метрик"),
    ] = "INFO"

    default_tags: Annotated[
        Dict[str, str],
        FieldMeta("Теги по умолчанию для всех метрик"),
    ] = {}

    retention_seconds: Annotated[
        float,
        FieldMeta("Время хранения метрик в памяти, сек"),
    ] = 3600.0
