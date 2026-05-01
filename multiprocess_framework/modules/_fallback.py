"""
Вспомогательный логгер для utility-классов без DI.

FallbackLogger живёт вне пакетов с логикой фреймворка, чтобы избежать
циклических импортов при загрузке (logger_module/__init__ → CRM → base_manager → cycle).

Использование в utility-классах (bootstrap, utility, без ObservableMixin):
    from ..._fallback import FallbackLogger
    _logger = FallbackLogger(__name__)
"""
import logging as _stdlib
from typing import Any


class FallbackLogger:
    """
    Lazy-wrapper: stdlib logging until LoggerManager is up, then routes through it.

    Заменяет паттерн `_logger = logging.getLogger(__name__)` в utility-классах.
    LoggerManager._instance проверяется лениво при каждом вызове.
    """

    __slots__ = ("_name", "_stdlib")

    def __init__(self, name: str) -> None:
        self._name = name
        self._stdlib = _stdlib.getLogger(name)

    def _lm(self) -> Any:
        try:
            from .logger_module.core.logger_manager import LoggerManager
            return LoggerManager._instance
        except Exception:
            return None

    def _fmt(self, msg: str, args: tuple) -> str:
        if args:
            try:
                return msg % args
            except Exception:
                return f"{msg} {args}"
        return msg

    def debug(self, msg: str, *args: Any) -> None:
        lm = self._lm()
        if lm:
            lm.debug(self._fmt(msg, args))
        else:
            self._stdlib.debug(msg, *args)

    def info(self, msg: str, *args: Any) -> None:
        lm = self._lm()
        if lm:
            lm.info(self._fmt(msg, args))
        else:
            self._stdlib.info(msg, *args)

    def warning(self, msg: str, *args: Any) -> None:
        lm = self._lm()
        if lm:
            lm.warning(self._fmt(msg, args))
        else:
            self._stdlib.warning(msg, *args)

    def error(self, msg: str, *args: Any) -> None:
        lm = self._lm()
        if lm:
            lm.error(self._fmt(msg, args))
        else:
            self._stdlib.error(msg, *args)

    def critical(self, msg: str, *args: Any) -> None:
        lm = self._lm()
        if lm:
            lm.critical(self._fmt(msg, args))
        else:
            self._stdlib.critical(msg, *args)
