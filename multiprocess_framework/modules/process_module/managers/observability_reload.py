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
from typing import TYPE_CHECKING, Any, Callable, Optional

from ...config_module.core.config import Config
from ..configs.observability_config import expand_observability

if TYPE_CHECKING:
    from ...config_module.tools.watcher import ConfigFileWatcher


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
    None-менеджеры пропускаются (например error/stats отключены).
    """

    def _on_reload(config: Config) -> None:
        section = config.get(section_key, {}) or {}
        expanded = expand_observability(section)
        if logger is not None:
            logger.reconfigure(expanded["logger"])
        if error is not None:
            error.reconfigure(expanded["error"])
        if stats is not None:
            stats.reconfigure(expanded["stats"])
        if log_info is not None:
            log_info(f"[observability] hot-reload применён (log_level={expanded['logger'].get('default_level')})")

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
) -> Optional["ConfigFileWatcher"]:
    """Запустить watcher файла конфига, перестраивающий менеджеры наблюдаемости.

    Args:
        config_path:  Путь к файлу конфига (например system.yaml) с секцией ``observability``.
        logger/error/stats: CRM-менеджеры с ``reconfigure(dict)`` (любой может быть None).
        section_key:  Имя секции в конфиге (по умолчанию ``observability``).
        debounce_seconds: Дебаунс watchdog (по умолчанию 1.0).
        log_info/log_error: Колбэки логирования (опционально).

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
