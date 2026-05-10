"""DatabaseAdapter — IPC/SQL facade для DatabaseService."""
from __future__ import annotations

from typing import Any, Optional

from multiprocess_framework.modules.process_module import ProcessIO
from sqlalchemy import text


class DatabaseAdapter:
    """Реализует DatabaseOutputPort: SQL + логи через ProcessIO."""

    def __init__(self, process) -> None:
        self._p = process  # нужен для прямого доступа к sql_manager
        self._io = ProcessIO(process)

    def execute_sql(self, sql: str, params: Optional[dict[str, Any]] = None) -> None:
        """Выполнить SQL через SQLManager (специфика БД, не IPC)."""
        self._p.sql_manager.execute(sql, params or {})

    def execute_many(self, sql: str, params: list[dict]) -> None:
        """Выполнить batch INSERT через транзакцию с executemany.

        SQLManager не имеет прямого executemany — используем uow().connection()
        для получения SQLAlchemy connection и вызываем executemany нативно.
        """
        if not params:
            return
        uow = self._p.sql_manager.uow()
        with uow.connection() as conn:
            conn.execute(text(sql), params)

    def log_info(self, text: str) -> None:
        self._io.log_info(text)

    def log_error(self, text: str) -> None:
        self._io.log_error(text)
