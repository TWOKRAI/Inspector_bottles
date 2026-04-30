"""Выходные порты базы данных."""
from __future__ import annotations
from typing import Any, Optional, Protocol


class DatabaseOutputPort(Protocol):
    """Порт для коммуникации DatabaseService с внешним миром."""

    def execute_sql(self, sql: str, params: Optional[dict[str, Any]] = None) -> None:
        """Выполнить SQL-запрос."""
        ...

    def execute_many(self, sql: str, params: list[dict]) -> None:
        """Выполнить batch INSERT через executemany."""
        ...

    def log_info(self, text: str) -> None:
        """Логирование информационного сообщения."""
        ...

    def log_error(self, text: str) -> None:
        """Логирование ошибки."""
        ...
