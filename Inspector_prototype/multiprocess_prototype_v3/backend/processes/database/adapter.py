"""DatabaseAdapter — IPC/SQL facade для DatabaseService."""
from __future__ import annotations

from typing import Any, Optional

from multiprocess_framework.modules.process_module import ProcessIO


class DatabaseAdapter:
    """Реализует DatabaseOutputPort: SQL + логи через ProcessIO."""

    def __init__(self, process) -> None:
        self._p = process  # нужен для прямого доступа к sql_manager
        self._io = ProcessIO(process)

    def execute_sql(self, sql: str, params: Optional[dict[str, Any]] = None) -> None:
        """Выполнить SQL через SQLManager (специфика БД, не IPC)."""
        self._p.sql_manager.execute(sql, params or {})

    def log_info(self, text: str) -> None:
        self._io.log_info(text)

    def log_error(self, text: str) -> None:
        self._io.log_error(text)
