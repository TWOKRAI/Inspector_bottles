# -*- coding: utf-8 -*-
"""Std-совместимый фасад над LoggerManager.

**Зачем.** Прикладной код (особенно GUI-слой прототипа) исторически написан в
стиле stdlib: ``logger = logging.getLogger(__name__)`` + ``logger.warning("%s", x)``.
В процессе фреймворка у корневого stdlib-логгера нет ни одного хендлера, поэтому
такие записи не попадают ни в ``logs/<proc>/*.log``, ни в консольный канал — они
уходят в ``logging.lastResort`` (stderr дочернего процесса) и на практике теряются.
Это класс «проглоченного сбоя»: следствие есть, следа нет.

Фасад даёт тот же вызов-интерфейс, но пишет в :class:`LoggerManager` процесса.
Замена в вызывающем коде — одна строка:

    -from logging import getLogger
    -logger = getLogger(__name__)
    +from multiprocess_framework.modules.logger_module import get_std_logger
    +logger = get_std_logger("gui")

**Почему не молча, если LoggerManager ещё не поднят.** Раньше локальные шимы в
таком случае просто выходили (``if lm is None: return``) — и сообщение исчезало
второй раз, уже по другой причине. Здесь вместо этого работает stdlib-фолбэк:
запись уходит в обычный ``logging``. Хуже, чем файл процесса, но не ноль.

**Резолв ленивый.** ``get_logger()`` вызывается на каждой записи, а не при
создании фасада: модули импортируются до ``init_logging()``, и связывание на
импорте навсегда зафиксировало бы фолбэк.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from ..core.logger_manager import get_logger
from ..utils import apply_format

__all__ = [
    "StdLoggerFacade",
    "get_std_logger",
]


class StdLoggerFacade:
    """Мост «вызов в стиле stdlib» → ``LoggerManager.<level>(msg, module=...)``.

    Поддерживает ``%``-форматирование аргументов, как stdlib: строка склеивается
    только когда запись действительно делается.

    Args:
        module: имя per-module файла LoggerManager (``gui``, ``trace``, ``camera``…
            см. ``LoggerManagerConfig.modules``). Незнакомое имя не ошибка —
            запись всё равно уйдёт в scope-каналы (console/system.log).
        fallback_name: имя stdlib-логгера для режима «LoggerManager не поднят».
            По умолчанию ``mpf.<module>``.
    """

    __slots__ = ("_module", "_fallback")

    def __init__(self, module: str = "main", *, fallback_name: str | None = None) -> None:
        self._module = module
        self._fallback = logging.getLogger(fallback_name or f"mpf.{module}")

    @property
    def module(self) -> str:
        """Имя per-module файла, в который пишет фасад."""
        return self._module

    # --- stdlib-совместимая поверхность ---

    def debug(self, msg: str, *args: Any) -> bool:
        return self._emit("debug", msg, args)

    def info(self, msg: str, *args: Any) -> bool:
        return self._emit("info", msg, args)

    def warning(self, msg: str, *args: Any) -> bool:
        return self._emit("warning", msg, args)

    def error(self, msg: str, *args: Any) -> bool:
        return self._emit("error", msg, args)

    def critical(self, msg: str, *args: Any) -> bool:
        return self._emit("critical", msg, args)

    def exception(self, msg: str, *args: Any) -> bool:
        """Как stdlib: ERROR + текущий traceback.

        У ``LoggerManager`` нет параметра ``exc_info``, поэтому traceback
        дописывается в текст сообщения — иначе он бы просто пропал.
        """
        text = self._format(msg, args)
        tb = traceback.format_exc()
        if tb and not tb.startswith("NoneType"):
            text = f"{text}\n{tb.rstrip()}"
        return self._emit("error", text, ())

    def log(self, level: str, msg: str, *args: Any) -> bool:
        """Запись с уровнем, заданным строкой (``"warning"``, ``"error"``…).

        Неизвестный уровень трактуется как ``info`` — потерять сообщение из-за
        опечатки в имени уровня хуже, чем записать его не тем уровнем.
        """
        name = level.lower()
        if name not in ("debug", "info", "warning", "error", "critical"):
            name = "info"
        return self._emit(name, msg, args)

    # --- Internal ---

    @staticmethod
    def _format(msg: str, args: tuple[Any, ...]) -> str:
        """Совместимость: правило форматирования переехало в ``logger_module.utils``.

        Метод оставлен потому, что ``exception()`` форматирует ДО эмиссии
        осознанно — ему нужен готовый текст, чтобы дописать traceback.
        """
        return apply_format(msg, args)

    def _emit(self, level: str, msg: str, args: tuple[Any, ...]) -> bool:
        """Записать. Returns: True если ушло в LoggerManager, False — в фолбэк.

        Ф1.5: ``msg % args`` здесь БОЛЬШЕ НЕ ВЫПОЛНЯЕТСЯ. Шаблон и аргументы
        уходят в менеджер как есть, и склейка происходит внутри ``log()`` —
        то есть строго после гейта. Раньше строка собиралась первой строкой
        метода, и выключенная группа всё равно стоила полного форматирования
        (а вместе с ним — всех ``__str__`` аргументов, что и есть настоящая
        цена на горячем пути GUI).

        Своего гейта здесь нет и не должно быть: он потребовал бы знать
        соответствие «уровень → скоуп», то есть завести вторую копию решения
        рядом с ``_LEVEL_DEFAULT_SCOPE``. Один гейт в менеджере — меньше слоёв
        и нечему разъезжаться.

        Фолбэк форматирует сам: у stdlib-логгера свой ленивый ``%``, но его
        правило на кривом шаблоне другое (сообщение теряется), а фасад обещает
        его сохранить.
        """
        lm = get_logger()
        if lm is None:
            getattr(self._fallback, level)(apply_format(msg, args))
            return False
        getattr(lm, level)(msg, self._module, *args)
        return True


_CACHE: dict[str, StdLoggerFacade] = {}


def get_std_logger(module: str = "main") -> StdLoggerFacade:
    """Вернуть (и закэшировать) фасад для указанного per-module файла.

    Кэш — по имени модуля: фасады не держат состояния кроме имени, а стабильная
    идентичность удобна в тестах (``assert a is b``).
    """
    facade = _CACHE.get(module)
    if facade is None:
        facade = StdLoggerFacade(module)
        _CACHE[module] = facade
    return facade
