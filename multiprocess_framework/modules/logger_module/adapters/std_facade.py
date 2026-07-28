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

**Резолв СВЯЗАННЫЙ, а не ленивый (2.2).** Прежняя редакция звала ``get_logger()``
на КАЖДОЙ записи — иначе связывание на импорте (модули грузятся до
``init_logging()``) навсегда зафиксировало бы фолбэк. Теперь связка ставится
один раз и обновляется по **эпохе наблюдаемости**
(:data:`~..core.logger_core.OBSERVABILITY_EPOCH`): она растёт при создании
процессного менеджера и при инвалидации кэша решений. Сравнение двух int'ов
вместо вызова + чтения атрибута класса — та же схема, что ``Logger._cache`` в
stdlib, чью семантику план и договорился копировать.

Связка включает и **пару «уровень → скоуп»**: вид зовёт ``LoggerCore.log``
напрямую, минуя удобные методы (``debug``/``info``/…). Замер 2026-07-27: сам
удобный метод стоит **219 нс** — больше, чем гейт, — на переупаковке
``*args``/``**extra``. Вид знает свой уровень с рождения, поэтому платить за
разбор уровня на каждой записи ему незачем.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, Optional, Tuple

from ..core.log_config import LogLevel, LogScope
from ..core.logger_core import OBSERVABILITY_EPOCH, _LEVEL_DEFAULT_SCOPE
from ..core.logger_manager import get_logger
from ..utils import apply_format

__all__ = [
    "StdLoggerFacade",
    "get_std_logger",
]

#: Уровень по имени метода → ``(scope, level)`` для прямого вызова ``log()``.
#:
#: Скоуп берётся из ``_LEVEL_DEFAULT_SCOPE`` — ТОЙ ЖЕ таблицы, по которой
#: выбирают скоуп удобные методы менеджера и отвечает предикат
#: ``is_enabled_for``. Своя копия соответствия здесь была бы вторым гейтом:
#: ровно то, чего прежняя редакция этого файла избегала, отказываясь от
#: собственного решения. Согласие с удобными методами закреплено тестом.
_LEVEL_ROUTE: Dict[str, Tuple[LogScope, LogLevel]] = {
    name.lower(): (_LEVEL_DEFAULT_SCOPE[level], level)
    for name, level in (
        ("debug", LogLevel.DEBUG),
        ("info", LogLevel.INFO),
        ("warning", LogLevel.WARNING),
        ("error", LogLevel.ERROR),
        ("critical", LogLevel.CRITICAL),
    )
}


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

    __slots__ = ("_module", "_fallback", "_writer", "_epoch")

    def __init__(self, module: str = "main", *, fallback_name: str | None = None) -> None:
        self._module = module
        self._fallback = logging.getLogger(fallback_name or f"mpf.{module}")
        # Связка ставится ЛЕНИВО, но один раз: вид переживает импорт до
        # init_logging(), а _bind() отработает на первой же записи.
        self._writer: Optional[Any] = None
        self._epoch: int = -1

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

        2.2: связка проверяется одним сравнением int'ов, а вызов идёт в
        ``log()`` напрямую — см. шапку модуля. Гейта здесь по-прежнему НЕТ, и
        это не оптимизация, которую забыли: короткое замыкание на стороне вида
        перестало бы двигать ``messages_processed``/``messages_skipped`` в
        менеджере, то есть купило бы наносекунды ценой правдивости счётчиков.
        Гейт дешевеет там, где он живёт, а не обходится снаружи.
        """
        if self._epoch != OBSERVABILITY_EPOCH[0]:
            self._bind()
        writer = self._writer
        if writer is None:
            getattr(self._fallback, level)(apply_format(msg, args))
            return False
        scope, log_level = _LEVEL_ROUTE[level]
        writer.log(scope, log_level, msg, self._module, *args)
        return True

    def _bind(self) -> None:
        """Пересвязаться с процессным менеджером и запомнить эпоху.

        Отдельный метод, а не тело в ``_emit``: он выполняется единицы раз за
        жизнь процесса, и держать его в горячем пути значило бы платить за
        его байткод на каждой записи.
        """
        self._writer = get_logger()
        self._epoch = OBSERVABILITY_EPOCH[0]


_CACHE: dict[tuple[str, str | None], StdLoggerFacade] = {}


def get_std_logger(module: str = "main", *, fallback_name: str | None = None) -> StdLoggerFacade:
    """Вернуть (и закэшировать) вид для указанного per-module файла.

    Кэш — по ПАРЕ ``(module, fallback_name)``, а не по одному имени модуля
    (2.2). Второй параметр появился, когда на этот вид переехал
    ``FallbackLogger``: ему нужен stdlib-логгер с ТОЧНЫМ именем модуля
    (``multiprocess_framework.modules...``), а не с префиксом ``mpf.``. Ключ по
    одному ``module`` отдал бы второму вызывающему чужой фолбэк молча — и
    записи ушли бы в stdlib-логгер с чужим именем ровно тогда, когда менеджера
    нет, то есть когда разбираться труднее всего.
    """
    key = (module, fallback_name)
    facade = _CACHE.get(key)
    if facade is None:
        facade = StdLoggerFacade(module, fallback_name=fallback_name)
        _CACHE[key] = facade
    return facade
