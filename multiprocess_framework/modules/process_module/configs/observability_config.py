# -*- coding: utf-8 -*-
"""
ObservabilityConfig — единый фасад над конфигами наблюдаемости.

Одна секция `observability` в конфиге процесса управляет Logger / Error / Stats /
Command вместо разрозненных Pydantic-defaults. ``expand_observability(dict)``
раскладывает её в ``{"logger": {...}, "error": {...}, "stats": {...}, "command": {...}}``
— словари, совместимые с ``LoggerManagerConfig`` / ``ErrorManagerConfig`` /
``StatsManagerConfig`` / (``command`` мержится в ``managers['command']`` и читается
``CommandManager`` напрямую — под ним нет отдельного manager-класса).

Это **фасад**, а не новые менеджеры: новых полей логики нет, expand только
переименовывает/группирует существующие. Dict at Boundary — между процессами едет dict.

Reuse-first: тогглы ``console``/``file`` переиспользуют дефолтный набор каналов
``LoggerManagerConfig`` (богатый граф scopes/per-module сохраняется), переключая лишь
``enabled`` у первичных каналов нужного типа — без дублирования дефолтов и без потери
per-module логов.

``commands.log_success`` (ADR-PM-018 в духе errors/stats-соседей, живая находка
2026-07-21): рутинный успех команды — не INFO-событие, на hot-path это тысячи строк/сек
(``command_manager.handle_command``). Гейт у ИСТОЧНИКА (CommandManager не форматирует
строку, если выключено), не фильтр на выходе. Дефолт — выключено. Ошибки/неуспех команд
эта секция не трогает — они логируются всегда, как errors всегда on в фасаде.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from pydantic import Field, field_validator

from ...channel_routing_module.buffers.batch_buffer import (
    DEFAULT_MAX_PENDING,
    DEFAULT_OVERFLOW_POLICY,
    validate_overflow_policy,
)
from ...data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("ObservabilityErrorsConfig")
class ObservabilityErrorsConfig(SchemaBase):
    """Под-секция ошибок (фасад над ErrorManagerConfig)."""

    enabled: Annotated[bool, FieldMeta("Создавать ErrorManager")] = True
    level: Annotated[str, FieldMeta("Минимальный уровень ошибок")] = "WARNING"
    include_stacktrace: Annotated[bool, FieldMeta("Включать stacktrace")] = True

    # Task 5.10.b — зеркало верхнеуровневого ``channels`` логгера. До неё
    # плоскость ошибок была адресуема ТОЛЬКО рантаймом: `sink.disable
    # manager=error` работал, но записать его было некуда, и любой
    # `config.reload` молча воскрешал снятый `errors_file`.
    channels: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных каналов ошибок ({имя: {enabled: false}})"),
    ] = Field(default_factory=dict)


@register_schema("ObservabilityStatsConfig")
class ObservabilityStatsConfig(SchemaBase):
    """Под-секция статистики (фасад над StatsManagerConfig)."""

    enabled: Annotated[bool, FieldMeta("Логировать метрики через LoggerManager")] = True
    aggregation_interval: Annotated[
        float,
        FieldMeta("Интервал агрегации, сек", min=0.1, max=60.0),
    ] = 5.0
    log_level: Annotated[str, FieldMeta("Уровень логирования метрик")] = "INFO"

    # Task 5.10.b — то же зеркало для третьей плоскости. Служебные имена
    # ``log_stats`` / ``file_stats`` описаний в ``channels`` не имеют (их
    # собирают свои сборщики) — но ``{enabled: false}`` про них теперь читается
    # (5.10.c): без этого ключ существовал бы, а гасил ровно ничего.
    channels: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных каналов статистики ({имя: {enabled: false}})"),
    ] = Field(default_factory=dict)


@register_schema("ObservabilityCommandsConfig")
class ObservabilityCommandsConfig(SchemaBase):
    """Под-секция логирования команд (фасад над CommandManagerConfig.log_success).

    Рутинный успех команды («Command 'X' executed successfully in Yс») — не
    ошибка и не редкое событие: на hot-path (``command_manager.handle_command``)
    это тысячи строк в секунду, и именно этот шум топил ротацию логов (живая
    находка 2026-07-21 — messages.log вырос до 645 МБ за один прогон). По
    умолчанию такие записи не производятся вовсе (не «пишем на DEBUG» — гейт
    у источника, строка не форматируется). Ошибки/неуспех команд эта секция
    не трогает — они логируются всегда, независимо от log_success.
    """

    log_success: Annotated[
        bool,
        FieldMeta("Логировать успешное выполнение команды (шумно на hot-path — по умолчанию выключено)"),
    ] = False


@register_schema("ObservabilityConfig")
class ObservabilityConfig(SchemaBase):
    """Единая секция наблюдаемости процесса (Logger + Error + Stats + Command)."""

    log_level: Annotated[str, FieldMeta("Уровень логирования по умолчанию")] = "INFO"
    log_directory: Annotated[
        Optional[str],
        FieldMeta("Корень логов (None — из env MULTIPROCESS_LOG_DIR / INSPECTOR_LOG_DIR)"),
    ] = None
    enable_batching: Annotated[bool, FieldMeta("Батчинг записи (Logger + Error)")] = True
    # Ф0.3: потолок буфера — операторский параметр, а не константа в коде. Без него
    # медленный сток копит записи в памяти без предела и без следа (см. batch_buffer.py).
    batch_max_pending: Annotated[
        int,
        FieldMeta("Потолок неотправленных записей на канал (0 — без потолка)", min=0, max=1_000_000),
    ] = DEFAULT_MAX_PENDING
    batch_overflow_policy: Annotated[
        str,
        FieldMeta("Что терять при переполнении: drop_oldest (кольцо) | drop_newest"),
    ] = DEFAULT_OVERFLOW_POLICY
    console: Annotated[bool, FieldMeta("Включить консольный sink")] = True
    file: Annotated[bool, FieldMeta("Включить файловые sink-каналы (первичные)")] = True

    # Task 5.12 — точечные переопределения ПОВЕРХ тогглов console/file.
    # Тоггл — оптовая ручка «все файловые», а слои требуют адресной: «снять
    # именно messages_file и пережить reload». Без этого поля рантайм-снятие
    # приёмника не выразимо декларативно, и оно жило рантайм-множеством,
    # которое пересборка не видела (блокер ревью 2.9). Форма — частичная:
    # словарь мержится поверх раскрытых каналов, а не заменяет их.
    channels: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных каналов логгера ({имя: {enabled: false}})"),
    ] = Field(default_factory=dict)
    scopes: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных скоупов логгера ({имя: {min_level: DEBUG}})"),
    ] = Field(default_factory=dict)

    # Task 5.8 — срок жизни рантайм-правки (слой L3). Поле схемы, а не константа
    # в коде: политика «сколько живёт ручка» машинно-специфична (на стенде час
    # уместен, на линии — нет), а значит обязана задаваться теми же слоями, что
    # и всё остальное. Раскладке в manager-конфиги НЕ подлежит — им про сессию
    # знать нечего; ключ читает только бухгалтерия слоёв.
    session_ttl_sec: Annotated[
        float,
        FieldMeta("Срок жизни рантайм-правки наблюдаемости, сек (0 — бессрочно)", min=0.0, max=86400.0),
    ] = 300.0

    # Ф0.7. Ротация ограничивает каждый файл, но не их число — за 82 дня
    # накопилось 730 файлов / 291 МБ без единого удаления. Обе политики
    # выключены по умолчанию: включать чистку молча нельзя.
    retention_days: Annotated[
        int,
        FieldMeta("Удалять логи старше N суток (0 — выключено)", min=0, max=3650),
    ] = 0
    retention_total_mb: Annotated[
        int,
        FieldMeta("Потолок суммарного веса каталога логов, МБ (0 — выключено)", min=0, max=1_000_000),
    ] = 0
    compress_rotated: Annotated[
        bool,
        FieldMeta("Сжимать ротированные бэкапы (foo.log.1 → foo.log.1.gz)"),
    ] = False

    errors: Annotated[
        ObservabilityErrorsConfig,
        FieldMeta("Секция ошибок"),
    ] = Field(default_factory=ObservabilityErrorsConfig)
    stats: Annotated[
        ObservabilityStatsConfig,
        FieldMeta("Секция статистики"),
    ] = Field(default_factory=ObservabilityStatsConfig)
    commands: Annotated[
        ObservabilityCommandsConfig,
        FieldMeta("Секция команд (CommandManager)"),
    ] = Field(default_factory=ObservabilityCommandsConfig)

    @field_validator("batch_overflow_policy")
    @classmethod
    def _check_overflow_policy(cls, value: str) -> str:
        """Отказ на границе конфига — до того, как правка коснётся менеджеров."""
        return validate_overflow_policy(value)


def _toggled_logger_channels(console: bool, file: bool) -> Dict[str, Dict[str, Any]]:
    """Дефолтные каналы LoggerManagerConfig с переключённым ``enabled`` по типу.

    Reuse: берём богатый граф каналов из дефолта LoggerManagerConfig (имена сохраняются,
    значит scopes продолжают резолвиться), флипаем только ``enabled`` для console/file.
    Ленивый импорт — избегаем цикла process_module ↔ logger_module на уровне модуля.
    """
    from ...logger_module.configs.logger_manager_config import LoggerManagerConfig

    result: Dict[str, Dict[str, Any]] = {}
    for name, ch in LoggerManagerConfig().channels.items():
        keep = console if ch.type == "console" else (file if ch.type == "file" else True)
        result[str(name)] = {**ch.model_dump(), "enabled": bool(ch.enabled and keep)}
    return result


def expand_observability(data: Any) -> Dict[str, Dict[str, Any]]:
    """Разложить секцию observability в четыре manager-конфига.

    Args:
        data: dict | ObservabilityConfig | None — единая секция. None/частичная → defaults.

    Returns:
        ``{"logger": {...}, "error": {...}, "stats": {...}, "command": {...}}`` —
        ``logger``/``error``/``stats`` валидны для соответствующего manager-конфига
        (``error`` всегда непустой — ErrorManager создаётся); ``command`` — сырой dict
        (``{"log_success": bool}``), мержится в ``proc_dict['managers']['command']``
        (см. ``managers_config.merge_managers`` + ``ManagersConfig``) и читается
        ``CommandManager`` напрямую — под ``command`` нет отдельного manager-класса,
        поэтому валидировать через Pydantic-конфиг здесь нечего.

        Ключ ``session_ttl_sec`` (Task 5.8) сюда НЕ раскладывается сознательно: это
        политика слоя L3, а не параметр менеджера — её читает
        ``ObservabilityLayers.effective_session_ttl``.
    """
    cfg = data if isinstance(data, ObservabilityConfig) else ObservabilityConfig.model_validate(data or {})

    logger: Dict[str, Any] = {
        "default_level": cfg.log_level,
        "enable_batching": cfg.enable_batching,
        "batch_max_pending": cfg.batch_max_pending,
        "batch_overflow_policy": cfg.batch_overflow_policy,
        # Ретеншен получает ТОЛЬКО logger: каталог логов один на процесс, и
        # второй подметальщик (error) означал бы два прохода по одному дереву
        # с гонкой за одни и те же файлы. Один каталог — один хозяин.
        "retention_days": cfg.retention_days,
        "retention_total_mb": cfg.retention_total_mb,
        "compress_rotated": cfg.compress_rotated,
    }
    # log_directory эмитим ТОЛЬКО если задан явно: при overlay-merge поверх дефолтов
    # None затёр бы уже резолвнутый абсолютный путь (managers_from_log_dir). None =
    # «не задано → использовать downstream-дефолт».
    if cfg.log_directory is not None:
        logger["log_directory"] = cfg.log_directory
    # Тогглы применяем только если что-то выключено — иначе LoggerManagerConfig
    # сам подставит дефолтные каналы (идентичный результат, меньше связности).
    if not (cfg.console and cfg.file):
        logger["channels"] = _toggled_logger_channels(cfg.console, cfg.file)
    # Task 5.12: адресные переопределения каналов/скоупов кладём ЧАСТИЧНЫМ словарём.
    # Он всегда попадает в deep-merge поверх полного набора (boot —
    # `merge_managers(base_managers, overlay)`, reload — merge поверх живого/базы),
    # поэтому неполная запись `{имя: {enabled: false}}` валидна: до Pydantic она
    # доезжает уже слитой. Заменять весь набор здесь нельзя — это стёрло бы
    # остальные каналы (ровно тот класс, что дал находку 2026-07-22 на каталоге).
    if cfg.channels:
        from ...data_schema_module import deep_merge

        logger["channels"] = deep_merge(logger.get("channels") or {}, cfg.channels)
    if cfg.scopes:
        logger["scopes"] = {str(k): dict(v) for k, v in cfg.scopes.items()}

    error: Dict[str, Any] = {
        "default_level": cfg.errors.level,
        "include_stacktrace": cfg.errors.include_stacktrace,
        "enable_batching": cfg.enable_batching,
        "batch_max_pending": cfg.batch_max_pending,
        "batch_overflow_policy": cfg.batch_overflow_policy,
    }

    stats: Dict[str, Any] = {
        "enable_logging": cfg.stats.enabled,
        "aggregation_interval": cfg.stats.aggregation_interval,
        "log_level": cfg.stats.log_level,
    }

    # Task 5.10.b: адресные переопределения каналов двух младших плоскостей —
    # тем же ЧАСТИЧНЫМ словарём, что у логгера. Полное описание канала здесь не
    # собирается сознательно: severity-каналы ошибок строит
    # ``expand_error_manager_config``, а служебные каналы статистики — её
    # собственные сборщики; наша запись обязана лечь поверх, а не вместо.
    if cfg.errors.channels:
        error["channels"] = {str(k): dict(v) for k, v in cfg.errors.channels.items()}
    if cfg.stats.channels:
        stats["channels"] = {str(k): dict(v) for k, v in cfg.stats.channels.items()}

    command: Dict[str, Any] = {
        "log_success": cfg.commands.log_success,
    }

    return {"logger": logger, "error": error, "stats": stats, "command": command}
