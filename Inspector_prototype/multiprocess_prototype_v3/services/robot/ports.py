"""Выходные порты робота."""
from __future__ import annotations
from typing import Protocol


class RobotOutputPort(Protocol):
    """Порт для коммуникации RobotService с внешним миром."""

    def write_log(self, text: str) -> None:
        """Записать лог-запись (файл или другой приёмник)."""
        ...

    def log_info(self, text: str) -> None:
        """Логирование информационного сообщения."""
        ...

    def log_error(self, text: str) -> None:
        """Логирование ошибки."""
        ...
