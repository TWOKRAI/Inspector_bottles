# -*- coding: utf-8 -*-
"""
StatsManagerConfig — конфигурация менеджера статистики.

Наследует ChannelRoutingConfig, добавляет параметры агрегации, flush,
логирования метрик и тегов по умолчанию.
"""

from typing import Annotated, Dict

from ...channel_routing_module import ChannelRoutingConfig
from ...data_schema_module import FieldMeta, register_schema
from ..channels.log_stats_channel import DEFAULT_LOG_LINE_MAX_BYTES


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

    # Р-3(б), B1: действующий темп записи = max(flush_interval, aggregation_interval),
    # и это ОБЪЯВЛЕНО здесь, а не спрятано в `stats_manager.__init__`. Пол оставлен
    # (совместимость темпа не ломается), но перестал действовать молча: при
    # срабатывании пишется WARNING с обоими числами, а действующий темп виден в
    # readback'е `introspect.observability -> effective.stats.aggregation_interval`
    # (читается из живого окна агрегации). Формула — `stats_manager.resolve_tempo`.
    aggregation_interval: Annotated[
        float,
        FieldMeta("Интервал агрегации, сек (действует max с flush_interval)", min=0.1, max=60.0),
    ] = 5.0

    flush_interval: Annotated[
        float,
        FieldMeta("ПОЛ интервала записи в каналы, сек — темп ниже него недостижим", min=1.0, max=300.0),
    ] = 10.0

    enable_logging: Annotated[
        bool,
        FieldMeta("Логировать метрики через LoggerManager"),
    ] = True

    log_level: Annotated[
        str,
        FieldMeta("Уровень логирования метрик"),
    ] = "INFO"

    # 3.4: непустой снапшот дампил весь список метрик в одну строку — медиана 2582,
    # максимум 53 900 байт по 416 живым строкам. Предел 2048 держит потолок фона на
    # 1.24 МиБ/ч (гейт этапа — ≤ ~2 МиБ/ч), сохраняя ~70 % метрик в такте; сколько
    # опущено — сказано в самой записи. 0 снимает предел для отладки.
    log_line_max_bytes: Annotated[
        int,
        FieldMeta("Предел объёма строки снапшота, байт (0 — без предела)", min=0, max=1_048_576),
    ] = DEFAULT_LOG_LINE_MAX_BYTES

    default_tags: Annotated[
        Dict[str, str],
        FieldMeta("Теги по умолчанию для всех метрик"),
    ] = {}

    retention_seconds: Annotated[
        float,
        FieldMeta("Время хранения метрик в памяти, сек"),
    ] = 3600.0
