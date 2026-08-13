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

#: Дефолт потолка серий (2.2). Живёт ЗДЕСЬ, в схеме, а не рядом с механизмом
#: (``core/cardinality_guard.py``): пакет ``core`` в момент импорта схемы ещё не
#: собран (его ``__init__`` тянет ``StatsManager``, а тот — эту самую схему), и
#: импорт оттуда даёт ``ImportError: partially initialized module``. Позиция
#: одна: и ``ObservabilityStatsConfig``, и ``resolve_max_series`` берут число
#: отсюда — вторая копия разошлась бы с первой на первой же правке дефолта.
#:
#: 1000 — ПРЕДОХРАНИТЕЛЬ от неограниченного роста, а не бюджет штатного режима:
#: измеренный максимум на 2026-08-13 — 384 серии на стартовом всплеске
#: ``devices`` и 226 в живом слое ``camera_0``. Потолок ниже 384 резал бы
#: законные данные старта. ``0`` снимает предел (как у ``log_line_max_bytes``).
DEFAULT_MAX_SERIES = 1000


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
        max_series           — потолок уникальных серий (имя × теги), 0 — без предела
        default_tags         — теги по умолчанию для всех метрик
        retention_seconds     — время хранения метрик в памяти, сек (НЕ подключено)
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

    # 2.2: потолок уникальных СЕРИЙ (имя × теги) — по одному стражу на окно
    # агрегации и на живой слой. Взрыв кардинальности дают теги, а не имена:
    # живой замер 2026-08-13 — 384 серии на 4 имени у `devices`, 226 серий на
    # 12 имён в живом слое `camera_0` за две минуты, и второй растёт весь срок
    # процесса. Обоснование дефолта — у DEFAULT_MAX_SERIES выше.
    max_series: Annotated[
        int,
        FieldMeta("Потолок уникальных серий метрик (имя × теги); 0 — без предела", min=0, max=1_000_000),
    ] = DEFAULT_MAX_SERIES

    default_tags: Annotated[
        Dict[str, str],
        FieldMeta("Теги по умолчанию для всех метрик"),
    ] = {}

    # Р2.2-11: ОБЪЯВЛЕН И МЁРТВ — не читает никто (проверено grep'ом на HEAD
    # 752f8b5e). Задача 2.2 его намеренно не подключает: ту же тревогу
    # («метрики копятся без предела») закрывает `max_series` счётом, а не
    # временем, и вторая дорога к одной цели разошлась бы с первой. Ручка,
    # которая ничего не делает, — та же ложь, что молчаливый no-op; названа в
    # ADR-SM-011 и уходит строкой в QUEUE.
    retention_seconds: Annotated[
        float,
        FieldMeta("Время хранения метрик в памяти, сек (НЕ ПОДКЛЮЧЕНО — см. ADR-SM-011)"),
    ] = 3600.0
