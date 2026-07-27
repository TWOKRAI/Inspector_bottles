# -*- coding: utf-8 -*-
"""Типы данных для logger_module."""

from dataclasses import dataclass
from typing import Any, Dict

from .log_config import LogLevel, LogScope


@dataclass
class LogRecord:
    """Запись лога — внутренний формат LoggerManager.

    Используется внутри процесса. При передаче через RouterManager
    конвертируется в Message(type=LOG) через to_dict().
    """

    timestamp: float
    level: LogLevel
    scope: LogScope
    message: str
    module: str
    extra: Dict[str, Any]
    seq: int = 0
    """Пломба (2.V1): номер записи в пределах процесса, ставится в точке эмиссии.

    Значение по умолчанию ``0`` означает «запись создана мимо
    :meth:`LoggerCore.log`» — то есть пломбы у неё нет и проверяющий обязан
    сказать об этом вслух, а не молча посчитать её отсутствие нормой.
    """

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для передачи через каналы / BatchBuffer."""
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,  # str: "ERROR", "INFO", ...
            "scope": self.scope.value,  # str: "system", "business", ...
            "message": self.message,
            "module": self.module,
            "extra": self.extra,
            "seq": self.seq,
        }
