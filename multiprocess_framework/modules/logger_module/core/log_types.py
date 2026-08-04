# -*- coding: utf-8 -*-
"""Типы данных для logger_module."""

from dataclasses import dataclass
from typing import Any, Dict

from .log_config import LogLevel, ScopeName


@dataclass
class LogRecord:
    """Запись лога — внутренний формат LoggerManager.

    Используется внутри процесса. При передаче через RouterManager
    конвертируется в Message(type=LOG) через to_dict().
    """

    timestamp: float
    level: LogLevel
    scope: ScopeName
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
            # Ф2.4: скоуп уже строка, и та же самая, что стоит ключом в конфиге.
            # До Ф2.4 здесь ехало `scope.value` — ВТОРОЕ написание того же имени
            # (`PERFORMANCE` в конфиге, `perf` в записи). Читателей у поля в
            # проде не было ни одного, поэтому сведение к одному написанию
            # обошлось без слоя совместимости (решение Р-2.4-А).
            "scope": self.scope,
            "message": self.message,
            "module": self.module,
            "extra": self.extra,
            "seq": self.seq,
        }
