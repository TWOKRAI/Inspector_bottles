"""
ActionLogRotation -- ротация таблицы action_log при превышении лимита записей.

При достижении max_count записей:
1. Создать архивную таблицу action_log_archive_{datetime}
2. Скопировать данные из action_log -> архив
3. Очистить action_log
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ActionLogRotation:
    """Ротация action_log -> archive при превышении max_count записей."""

    def __init__(
        self,
        adapter: object,
        *,
        max_count: int = 10_000,
    ) -> None:
        """
        Args:
            adapter: ISyncEngineAdapter для SQL-операций.
            max_count: Порог для ротации (по умолчанию 10 000).
        """
        self._adapter = adapter
        self._max_count = max_count

    def maybe_rotate(self, current_count: int) -> bool:
        """Ротировать если current_count >= max_count.

        Returns:
            True если ротация была выполнена.
        """
        if current_count < self._max_count:
            return False

        try:
            self._do_rotate()
            return True
        except Exception:
            logger.exception("Ошибка ротации action_log")
            return False

    def _do_rotate(self) -> None:
        """Создать архив и очистить action_log."""
        archive_name = f"action_log_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # SQLite: CREATE TABLE AS + DELETE
        sql_create_archive = (
            f"CREATE TABLE IF NOT EXISTS {archive_name} AS SELECT * FROM action_log"
        )
        sql_clear = "DELETE FROM action_log"

        # Выполняем через adapter
        adapter = self._adapter
        if hasattr(adapter, "execute"):
            adapter.execute(sql_create_archive)
            adapter.execute(sql_clear)
            logger.info(
                "Ротация action_log -> %s завершена",
                archive_name,
            )
        elif hasattr(adapter, "connection"):
            # Через connection context manager
            with adapter.connection() as conn:
                conn.execute(sql_create_archive)
                conn.execute(sql_clear)
                conn.commit()
            logger.info(
                "Ротация action_log -> %s завершена",
                archive_name,
            )
        else:
            logger.error("ActionLogRotation: adapter не поддерживает execute/connection")
