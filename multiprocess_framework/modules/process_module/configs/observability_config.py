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

from pydantic import Field

from ...data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("ObservabilityErrorsConfig")
class ObservabilityErrorsConfig(SchemaBase):
    """Под-секция ошибок (фасад над ErrorManagerConfig)."""

    enabled: Annotated[bool, FieldMeta("Создавать ErrorManager")] = True
    level: Annotated[str, FieldMeta("Минимальный уровень ошибок")] = "WARNING"
    include_stacktrace: Annotated[bool, FieldMeta("Включать stacktrace")] = True


@register_schema("ObservabilityStatsConfig")
class ObservabilityStatsConfig(SchemaBase):
    """Под-секция статистики (фасад над StatsManagerConfig)."""

    enabled: Annotated[bool, FieldMeta("Логировать метрики через LoggerManager")] = True
    aggregation_interval: Annotated[
        float,
        FieldMeta("Интервал агрегации, сек", min=0.1, max=60.0),
    ] = 5.0
    log_level: Annotated[str, FieldMeta("Уровень логирования метрик")] = "INFO"


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
    console: Annotated[bool, FieldMeta("Включить консольный sink")] = True
    file: Annotated[bool, FieldMeta("Включить файловые sink-каналы (первичные)")] = True

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
    """
    cfg = data if isinstance(data, ObservabilityConfig) else ObservabilityConfig.model_validate(data or {})

    logger: Dict[str, Any] = {
        "default_level": cfg.log_level,
        "enable_batching": cfg.enable_batching,
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

    error: Dict[str, Any] = {
        "default_level": cfg.errors.level,
        "include_stacktrace": cfg.errors.include_stacktrace,
        "enable_batching": cfg.enable_batching,
    }

    stats: Dict[str, Any] = {
        "enable_logging": cfg.stats.enabled,
        "aggregation_interval": cfg.stats.aggregation_interval,
        "log_level": cfg.stats.log_level,
    }

    command: Dict[str, Any] = {
        "log_success": cfg.commands.log_success,
    }

    return {"logger": logger, "error": error, "stats": stats, "command": command}
