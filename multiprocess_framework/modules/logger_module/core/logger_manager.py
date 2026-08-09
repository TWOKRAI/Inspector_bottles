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
from .logger_core import (  # noqa: F401 — re-export (стабильный публичный путь)
    LoggerCore,
    bump_observability_epoch,
    contextualize,
    log_context,
)


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
        # 2.2: связанные виды держат указатель на менеджер процесса. Смена
        # синглтона обязана объявить их связки устаревшими — иначе вид продолжил
        # бы писать в закрытый менеджер, а его записи исчезали бы молча.
        bump_observability_epoch()
        # Ф6.х.2: новый менеджер — раннее накопление снова законно.
        # Импорт ленивый: std_facade импортирует этот модуль (get_logger).
        from ..adapters.std_facade import reopen_early_buffer

        reopen_early_buffer()

    def shutdown(self) -> bool:
        """Закрыться и снять себя с ``_instance`` (Ф6.8).

        Раньше синглтон переживал собственный ``shutdown()``: ``get_logger()``
        продолжал отдавать закрытый менеджер, и всё, что писало через связанный
        вид, уходило в закрытые каналы — то есть в никуда, и молча. Симптом
        поймали тесты 6.8: ``QueueRegistry`` перевели с мёртвого stdlib-логгера
        на вид, и его записи начали исчезать ровно в том прогоне, где до этого
        успел закрыться чужой менеджер.

        Снятие идёт ПОСЛЕ ``super().shutdown()``: тот пишет прощальную запись
        через себя же, и с уже обнулённым указателем она потерялась бы.
        Проверка ``is self`` обязательна — если процесс успел поднять новый
        менеджер, закрытие старого не имеет права его отцепить.
        """
        result = super().shutdown()
        if LoggerManager._instance is self:
            LoggerManager._instance = None
            # Связки видов указывают на закрытый менеджер — объявляем
            # устаревшими, чтобы следующая запись ушла в stdlib-фолбэк,
            # а не в закрытые каналы.
            bump_observability_epoch()
            # Ф6.х.2 (решение владельца): после штатного снятия менеджера буфер
            # ранних записей ЗАКРЫВАЕТСЯ — записи процесса, пережившего
            # shutdown() логгера, дропаются со счётчиком, а не копятся навсегда
            # и не утекают «стартовыми» в следующий менеджер.
            from ..adapters.std_facade import close_early_buffer

            close_early_buffer()
        return result


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
