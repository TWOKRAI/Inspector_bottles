# -*- coding: utf-8 -*-
"""
Observability hot-reload: ConfigFileWatcher → reconfigure(Logger/Error/Stats).

Связывает готовые компоненты (reuse-first, нового watcher-кода нет):
  ConfigFileWatcher (config_module) следит за файлом конфига → при изменении читает
  секцию ``observability`` → зовёт ``reconfigure()`` у CRM-менеджеров (Phase 1).

Размещение (ADR observability P3.3): один watcher живёт в оркестраторе
(ProcessManagerProcess) и перестраивает ЕГО менеджеры. Cross-process распространение —
через IPC ``config.reload`` (Phase 4): watcher остаётся здесь, дети получат IPC-хендлер.

Итерация 1: full-rebuild каналов в потоке watchdog. Правки конфига редки и дебаунсятся,
поэтому отдельная синхронизация reconfigure ↔ конкурентного логирования не вводится
(задел следующей итерации).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from ...config_module.core.config import Config
from ..configs.observability_config import expand_observability

if TYPE_CHECKING:
    from ...config_module.tools.watcher import ConfigFileWatcher


def _current_manager_config(manager: Any) -> Optional[Dict[str, Any]]:
    """Живой конфиг менеджера как dict (база для merge) или None, если недоступен."""
    cfg = getattr(manager, "config", None)
    if cfg is None:
        return None
    dump = getattr(cfg, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:  # noqa: BLE001 — недампящийся конфиг: применяем без merge
            return None
    return dict(cfg) if isinstance(cfg, dict) else None


def _level_profile_scopes(level: str) -> Dict[str, Dict[str, Any]]:
    """Scopes-профиль под глобальный ``log_level`` (иначе уровень — мёртвый параметр).

    ``default_level`` сам по себе НЕ фильтрует: решение принимает ``min_level``
    КАЖДОГО скоупа, а все стандартные скоупы всегда присутствуют в конфиге —
    поэтому смена уровня обязана переписывать их пороги:

      - ``INFO``  — штатный настроенный профиль (дефолты LoggerManagerConfig:
        SYSTEM=WARNING на консоль, BUSINESS/PERFORMANCE=INFO, DEBUG-scope выключен);
      - ``DEBUG`` — все скоупы на DEBUG + DEBUG-scope включается (firehose осознанно);
      - ``WARNING``/``ERROR``/``CRITICAL`` — пороги всех скоупов поднимаются до уровня
        (DEBUG-scope остаётся выключенным).
    """
    from ...logger_module.configs.logger_manager_config import LoggerManagerConfig

    lvl = str(level).upper()
    scopes: Dict[str, Dict[str, Any]] = {}
    for name, sc in LoggerManagerConfig().scopes.items():
        d = sc.model_dump()
        if lvl == "DEBUG":
            d["min_level"] = "DEBUG"
            d["enabled"] = True
        elif lvl != "INFO":
            d["min_level"] = lvl
        scopes[name] = d
    return scopes


def observability_effective(
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
) -> Dict[str, Any]:
    """Фактическое (readback) состояние менеджеров наблюдаемости — не эхо запроса.

    Читается из ЖИВЫХ менеджеров ПОСЛЕ применения: пороги скоупов логгера,
    каталог логов, активные каналы (реестр каналов — он отражает и runtime
    ``logger.sink.enable/disable``, чего конфиг не видит), уровень ошибок,
    включённость статистики.
    """
    out: Dict[str, Any] = {}
    if logger is not None and getattr(logger, "config", None) is not None:
        lc = logger.config
        section: Dict[str, Any] = {
            "default_level": getattr(lc, "default_level", None),
            "log_directory": getattr(lc, "log_directory", None),
        }
        scopes = getattr(lc, "scopes", None)
        if isinstance(scopes, dict):
            section["scopes"] = {
                str(k): {
                    "enabled": bool(getattr(v, "enabled", True)),
                    "min_level": getattr(v, "min_level", None),
                }
                for k, v in scopes.items()
            }
        registry = getattr(logger, "_channel_registry", None)
        names = getattr(registry, "names", None)
        if callable(names):
            try:
                section["channels_active"] = sorted(names())
            except Exception:  # noqa: BLE001 — readback best-effort
                pass
        out["logger"] = section
    if error is not None and getattr(error, "config", None) is not None:
        out["error"] = {"default_level": getattr(error.config, "default_level", None)}
    if stats is not None and getattr(stats, "config", None) is not None:
        sc = stats.config
        out["stats"] = {
            "enable_logging": getattr(sc, "enable_logging", None),
            "aggregation_interval": getattr(sc, "aggregation_interval", None),
        }
    return out


def apply_observability_reconfigure(
    section: Any,
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    log_info: Optional[Callable[[str], None]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Применить секцию ``observability`` к менеджерам через ``reconfigure`` (единый путь).

    ЕДИНСТВЕННОЕ место, где секция раскладывается (``expand_observability``) и
    применяется (``reconfigure``). И hot-reload watcher (см.
    :func:`make_observability_on_reload`), и IPC-команда ``config.reload`` (Ф1 Task 1.4)
    зовут именно эту функцию — поэтому файловый и IPC-пути НЕ конфликтуют.

    Семантика — ДЕЛЬТА ПОВЕРХ ЖИВОГО, не сброс: раскрытая секция мержится на
    текущий конфиг каждого менеджера (``deep_merge``). Частичная секция
    (``{"log_level": "DEBUG"}``) больше НЕ теряет ``log_directory``/каналы/скоупы,
    молча пересобирая их из дефолтов (живая находка 2026-07-22: reload уводил
    файлы логов в чужой каталог). Явный ``log_level`` дополнительно переписывает
    пороги скоупов профилем :func:`_level_profile_scopes` — без этого смена уровня
    была no-op'ом (``default_level`` — лишь fallback для отсутствующих скоупов).

    None-менеджеры пропускаются (например error/stats отключены).

    Returns:
        Разложенный ПРИМЕНЁННЫЙ конфиг ``{"logger": {...}, "error": {...}, "stats": {...}}``
        (после merge) — вызывающий может отдать наружу ``log_level`` (диагностика).
        Фактическое состояние менеджеров — :func:`observability_effective`.
    """
    from ...data_schema_module import deep_merge

    expanded = expand_observability(section or {})
    raw = section if isinstance(section, dict) else {}
    explicit_level = raw.get("log_level")

    def _merged(manager: Any, target: Dict[str, Any]) -> Dict[str, Any]:
        current = _current_manager_config(manager)
        return deep_merge(current, target) if current else target

    if logger is not None:
        logger_cfg = _merged(logger, expanded["logger"])
        if explicit_level is not None:
            logger_cfg["scopes"] = _level_profile_scopes(explicit_level)
            logger_cfg["default_level"] = str(explicit_level).upper()
        expanded["logger"] = logger_cfg
        logger.reconfigure(logger_cfg)
    if error is not None:
        expanded["error"] = _merged(error, expanded["error"])
        error.reconfigure(expanded["error"])
    if stats is not None:
        expanded["stats"] = _merged(stats, expanded["stats"])
        stats.reconfigure(expanded["stats"])
    if log_info is not None:
        log_info(f"[observability] reconfigure применён (log_level={expanded['logger'].get('default_level')})")
    return expanded


def make_observability_on_reload(
    *,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    section_key: str = "observability",
    log_info: Optional[Callable[[str], None]] = None,
) -> Callable[[Config], None]:
    """Собрать ``on_reload(config)`` callback: секция ``observability`` → reconfigure 3 менеджеров.

    Использует ``on_reload`` ConfigFileWatcher'а напрямую (callback вызывается ПОСЛЕ
    ``Config.update``) — pub/sub по ключу не нужен (``update`` шлёт ``_notify("*")``).
    Делегирует применение в :func:`apply_observability_reconfigure` — общий путь с
    IPC ``config.reload`` (гарантия неконфликта watcher ↔ IPC).
    """

    def _on_reload(config: Config) -> None:
        section = config.get(section_key, {}) or {}
        apply_observability_reconfigure(
            section,
            logger=logger,
            error=error,
            stats=stats,
            log_info=log_info,
        )

    return _on_reload


def start_observability_watcher(
    *,
    config_path: str | Path,
    logger: Any = None,
    error: Any = None,
    stats: Any = None,
    section_key: str = "observability",
    debounce_seconds: float = 1.0,
    log_info: Optional[Callable[[str], None]] = None,
    log_error: Optional[Callable[[str], None]] = None,
    on_reload_extra: Optional[Callable[[Config], None]] = None,
) -> Optional["ConfigFileWatcher"]:
    """Запустить watcher файла конфига, перестраивающий менеджеры наблюдаемости.

    Args:
        config_path:  Путь к файлу конфига (например system.yaml) с секцией ``observability``.
        logger/error/stats: CRM-менеджеры с ``reconfigure(dict)`` (любой может быть None).
        section_key:  Имя секции в конфиге (по умолчанию ``observability``).
        debounce_seconds: Дебаунс watchdog (по умолчанию 1.0).
        log_info/log_error: Колбэки логирования (опционально).
        on_reload_extra: Дополнительный ``on_reload(config)``-колбэк, вызываемый ПОСЛЕ
            observability-reconfigure на том же ``Config`` (PC 3.1: оркестратор передаёт
            сюда telemetry-throttle-колбэк из ``telemetry_reload.make_telemetry_on_reload``,
            чтобы одна правка файла перестроила и observability-менеджеры, и центральный
            троттл). ``None`` → только observability (прежнее поведение). Семантически
            watcher остаётся observability-агностичным к содержимому extra-колбэка.

    Returns:
        Запущенный ``ConfigFileWatcher`` или None, если файл не найден.
    """
    from ...data_schema_module.serialization.converter import DataConverter

    path = Path(config_path)
    if not path.exists():
        if log_error is not None:
            log_error(f"[observability] hot-reload: файл не найден — {path}")
        return None

    # Ленивый импорт: watchdog — опциональная зависимость; без неё hot-reload недоступен,
    # но импорт process_module не должен падать.
    try:
        from ...config_module.tools.watcher import ConfigFileWatcher
    except ImportError:
        if log_error is not None:
            log_error("[observability] hot-reload недоступен: не установлен watchdog")
        return None

    # Начальное содержимое — текущий файл (чтобы config.get(section) был консистентен).
    try:
        initial = DataConverter.load_from_file(path)
        initial = initial if isinstance(initial, dict) else {}
    except Exception:
        initial = {}

    config = Config(initial_data=initial)
    on_reload = make_observability_on_reload(
        logger=logger,
        error=error,
        stats=stats,
        section_key=section_key,
        log_info=log_info,
    )
    if on_reload_extra is not None:
        # Композиция: сначала observability-reconfigure, затем extra-колбэк (PC 3.1:
        # telemetry-throttle) на том же Config. Наличие callback'а — child-side seam,
        # содержимого extra эта функция не знает (остаётся observability-агностичной).
        _base_on_reload = on_reload

        def on_reload(config: Config, _base=_base_on_reload, _extra=on_reload_extra) -> None:  # noqa: F811
            _base(config)
            _extra(config)

    watcher = ConfigFileWatcher(
        path=path,
        config=config,
        on_reload=on_reload,
        debounce_seconds=debounce_seconds,
    )
    watcher.start()
    if log_info is not None:
        log_info(f"[observability] hot-reload watcher запущен: {path}")
    return watcher
