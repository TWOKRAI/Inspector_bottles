"""
ActionLogRepository -- репозиторий для персистентного хранения Action.

Обёртка над GenericRepository[ActionLogRow], предоставляющая
доменный API: append, find_recent, find_since, count, delete_before.

Конвертация Action <-> ActionLogRow происходит внутри репозитория,
вызывающий код работает только с Action.
"""

from __future__ import annotations

from Services.sql.core.base_repository import GenericRepository
from Services.sql.interfaces import ISyncEngineAdapter

from multiprocess_framework.modules.actions_module.schemas import Action
from .schema_ext import ActionLogRow, from_action_log_row, to_action_log_row


class ActionLogRepository:
    """Персистентный лог действий в таблице action_log.

    Использует GenericRepository для базового CRUD,
    добавляя доменные методы с ORDER BY / LIMIT / WHERE timestamp.
    """

    def __init__(self, adapter: ISyncEngineAdapter) -> None:
        """Инициализировать репозиторий.

        Args:
            adapter: синхронный адаптер движка БД (ISyncEngineAdapter).
        """
        self._repo = GenericRepository(
            adapter=adapter,
            schema_class=ActionLogRow,
            id_column="action_id",
        )
        self._adapter = adapter
        self._table = "action_log"

    def append(self, action: Action) -> None:
        """Сохранить Action в БД.

        Конвертирует Action -> ActionLogRow и вставляет запись.
        """
        row = to_action_log_row(action)
        self._repo.insert(row)

    def find_recent(self, n: int = 200) -> list[Action]:
        """Получить n последних действий, отсортированных по timestamp DESC.

        Возвращает список Action (от новейшего к старейшему).
        """
        sql = f'SELECT * FROM "{self._table}" ORDER BY "timestamp" DESC LIMIT :limit'
        rows = self._adapter.query(sql, {"limit": n})
        return [from_action_log_row(ActionLogRow.model_validate(r)) for r in rows]

    def find_since(self, timestamp: float) -> list[Action]:
        """Получить все действия с timestamp >= заданного.

        Используется для recovery: восстановление действий после определённого момента.
        Результат отсортирован по timestamp ASC (хронологический порядок).
        """
        sql = f'SELECT * FROM "{self._table}" WHERE "timestamp" >= :ts ORDER BY "timestamp" ASC'
        rows = self._adapter.query(sql, {"ts": timestamp})
        return [from_action_log_row(ActionLogRow.model_validate(r)) for r in rows]

    def count(self) -> int:
        """Получить общее количество записей в action_log."""
        sql = f'SELECT COUNT(*) AS cnt FROM "{self._table}"'
        rows = self._adapter.query(sql)
        if rows:
            return int(rows[0].get("cnt", 0))
        return 0

    def delete_before(self, timestamp: float) -> int:
        """Удалить записи с timestamp < заданного (ротация лога).

        Returns:
            Количество удалённых строк.
        """
        sql = f'DELETE FROM "{self._table}" WHERE "timestamp" < :ts'
        return self._adapter.execute(sql, {"ts": timestamp})
