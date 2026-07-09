# -*- coding: utf-8 -*-
"""
LoggerManager — тонкий наследник LoggerCore с process-wide singleton.

Task 5.14 (CRM-развязка):
  - Весь лог-слой вынесен в :class:`LoggerCore` (общий предок LoggerManager и
    ErrorManager — композиция общего слоя вместо Logger←Error IS-A).
  - LoggerManager добавляет ТОЛЬКО process-wide singleton (``_instance``), чтобы
    :func:`get_logger` возвращал именно логгер процесса, а НЕ ErrorManager-брата
    (создание ErrorManager больше не перетирает singleton).

Публичные пути импорта СОХРАНЕНЫ (их использует весь фреймворк):
  ``LoggerManager``, ``get_logger``, ``init_logging``, ``shutdown_logging``,
  ``log_context`` доступны из этого модуля как прежде.
"""

from typing import Any, Optional

from ..configs.logger_manager_config import LoggerManagerConfig
from .logger_core import LoggerCore, log_context  # noqa: F401 — re-export (стабильный публичный путь)


class LoggerManager(LoggerCore):
    """Менеджер логирования процесса — LoggerCore + process-wide singleton.

    Единственное отличие от :class:`LoggerCore` — привязка ``_instance`` в конце
    ``__init__``. Благодаря выделению общего слоя в LoggerCore создание
    ``ErrorManager`` (брат, тоже потомок LoggerCore) НЕ перетирает этот singleton.
    """

    _instance: Optional["LoggerManager"] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        LoggerManager._instance = self


# =========================================================================
# Глобальные функции
# =========================================================================


def get_logger() -> Optional[LoggerManager]:
    return LoggerManager._instance


def init_logging(config: LoggerManagerConfig, **kwargs) -> LoggerManager:
    return LoggerManager(config=config, **kwargs)


def shutdown_logging():
    logger = get_logger()
    if logger:
        logger.shutdown()
