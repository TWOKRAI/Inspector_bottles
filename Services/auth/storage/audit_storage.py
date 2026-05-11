# -*- coding: utf-8 -*-
"""
SqliteAuditStorage — хранилище сессий и аудит-лога на SQLite.

Использует Services/sql (GenericRepository + DDLBuilder + create_sync_adapter)
поверх SQLite-файла или in-memory БД (для тестов).

Инварианты:
    - AuditEntry: UPDATE и DELETE запрещены → AuditImmutableError (AUTH-007).
    - SessionEntry: без ограничений (logout обновляет поле logout_at).
    - ensure_schema(): идемпотентный CREATE TABLE IF NOT EXISTS.

Пример использования:
    storage = SqliteAuditStorage("sqlite:///audit.db")
    storage.ensure_schema()

    entry = AuditEntry.with_truncation(
        entry_id=str(uuid4()),
        ts=datetime.now(timezone.utc),
        user_id="u1",
        username="alice",
        action_type="field_update",
    )
    storage.append_audit(entry)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from sqlalchemy import text

from Services.sql import DDLBuilder, GenericRepository
from Services.sql.adapters.schema_mapper import SchemaBaseMapper
from Services.sql.adapters.sync_adapter import BaseSyncAdapter
from Services.sql.configs import SQLManagerConfig

from ..exceptions import AuditImmutableError
from ..models import AuditEntry, SessionEntry


# =============================================================================
# Внутренние вспомогательные классы — репозитории с нужными ограничениями
# =============================================================================


class _AppendOnlyAuditRepo(GenericRepository):
    """
    Репозиторий для AuditEntry с запретом UPDATE и DELETE.

    Переопределяет родительские методы update() и delete() так, чтобы
    они всегда выбрасывали AuditImmutableError.
    """

    def update(self, id: Any, entity: Any) -> Any:
        """Запрещено — аудит-лог неизменяемый."""
        raise AuditImmutableError(
            "Изменение записей аудит-лога запрещено (append-only инвариант).",
            entry_id=str(id),
        )

    def delete(self, id: Any) -> bool:
        """Запрещено — аудит-лог неизменяемый."""
        raise AuditImmutableError(
            "Удаление записей аудит-лога запрещено (append-only инвариант).",
            entry_id=str(id),
        )


# =============================================================================
# Публичный класс
# =============================================================================


class SqliteAuditStorage:
    """
    Хранилище сессий и аудит-лога на SQLite.

    Обёртка двух GenericRepository: один — для AuditEntry (append-only),
    другой — для SessionEntry (обычный CRUD, logout обновляет logout_at).

    Args:
        db_url: SQLAlchemy URL к SQLite.
                Например: ``"sqlite:///path/to/audit.db"``
                или ``"sqlite:///:memory:"`` для тестов.
    """

    def __init__(self, db_url: str = "sqlite:///:memory:") -> None:
        self._db_url = db_url
        self._mapper = SchemaBaseMapper()
        self._ddl = DDLBuilder(self._mapper)

        # Создаём единый адаптер — один SQLite-файл / одна memory-БД
        config = SQLManagerConfig(url=db_url, dialect="sqlite")
        self._adapter = BaseSyncAdapter(config)
        self._adapter.setup()

        # Репозиторий сессий — обычный CRUD
        self._sessions: GenericRepository = GenericRepository(
            adapter=self._adapter,
            schema_class=SessionEntry,
            table_name="auth_sessions",
            id_column="session_id",
            schema_mapper=self._mapper,
        )

        # Репозиторий аудит-лога — append-only
        self._audit: _AppendOnlyAuditRepo = _AppendOnlyAuditRepo(
            adapter=self._adapter,
            schema_class=AuditEntry,
            table_name="audit_log",
            id_column="entry_id",
            schema_mapper=self._mapper,
        )

    # =========================================================================
    # Инициализация схемы
    # =========================================================================

    def ensure_schema(self) -> None:
        """
        Создать таблицы и индексы если они ещё не существуют.

        Идемпотентен: повторный вызов не ломает существующую схему и данные.
        Использует ``CREATE TABLE IF NOT EXISTS`` и ``CREATE INDEX IF NOT EXISTS``.
        """
        stmts: list[str] = []
        stmts.extend(self._ddl.build_create_table(SessionEntry, dialect="sqlite"))
        stmts.extend(self._ddl.build_create_table(AuditEntry, dialect="sqlite"))

        with self._adapter._engine.connect() as conn:  # type: ignore[union-attr]
            for stmt in stmts:
                conn.execute(text(stmt))
            conn.commit()

    # =========================================================================
    # API аудит-лога (append-only)
    # =========================================================================

    def append_audit(self, entry: AuditEntry) -> None:
        """
        Записать событие аудита.

        Args:
            entry: Экземпляр AuditEntry. Рекомендуется создавать через
                   ``AuditEntry.with_truncation(...)`` для автоусечения JSON.

        Raises:
            Propagates любые SQLAlchemy-исключения при проблемах с БД.
        """
        self._audit.insert(entry)

    # =========================================================================
    # API сессий
    # =========================================================================

    def append_session(self, entry: SessionEntry) -> None:
        """
        Записать открытие новой сессии.

        Args:
            entry: Экземпляр SessionEntry с заполненными session_id, user_id,
                   username, login_at.
        """
        self._sessions.insert(entry)

    def close_session(self, session_id: str, logout_at: datetime) -> None:
        """
        Зафиксировать завершение сессии (запись logout_at).

        Если сессия с данным session_id не найдена — операция игнорируется
        (сессия могла быть закрыта повторно или удалена).

        Args:
            session_id: UUID4 идентификатор сессии.
            logout_at:  UTC-метка времени выхода.
        """
        existing = self._sessions.find_by_id(session_id)
        if existing is None:
            return
        updated = existing.model_copy(update={"logout_at": logout_at})
        self._sessions.update(session_id, updated)

    # =========================================================================
    # Запросы
    # =========================================================================

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[SessionEntry]:
        """
        Получить список сессий.

        Args:
            user_id: Фильтр по пользователю. None — сессии всех пользователей.
            limit:   Максимальное количество записей (по умолчанию 50).

        Returns:
            Список SessionEntry, отсортированных по login_at DESC.
        """
        if user_id is not None:
            sql = (
                'SELECT * FROM "auth_sessions" WHERE "user_id" = :user_id '
                'ORDER BY "login_at" DESC LIMIT :limit'
            )
            rows = self._adapter.query(sql, {"user_id": user_id, "limit": limit})
        else:
            sql = (
                'SELECT * FROM "auth_sessions" '
                'ORDER BY "login_at" DESC LIMIT :limit'
            )
            rows = self._adapter.query(sql, {"limit": limit})

        return [SessionEntry.model_validate(row) for row in rows]

    def list_audit(
        self,
        *,
        user_id: Optional[str] = None,
        resource: Optional[str] = None,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """
        Получить список записей аудит-лога с фильтрами.

        Args:
            user_id:  Фильтр по пользователю (точное совпадение).
            resource: Фильтр по ресурсу (точное совпадение).
            from_dt:  Нижняя граница временного диапазона (включительно).
            to_dt:    Верхняя граница временного диапазона (включительно).
            limit:    Максимальное количество записей (по умолчанию 100).
            offset:   Смещение для пагинации (по умолчанию 0).

        Returns:
            Список AuditEntry, отсортированных по ts DESC.
        """
        conditions: list[str] = []
        params: Dict[str, Any] = {"limit": limit, "offset": offset}

        if user_id is not None:
            conditions.append('"user_id" = :user_id')
            params["user_id"] = user_id

        if resource is not None:
            conditions.append('"resource" = :resource')
            params["resource"] = resource

        if from_dt is not None:
            conditions.append('"ts" >= :from_dt')
            params["from_dt"] = from_dt

        if to_dt is not None:
            conditions.append('"ts" <= :to_dt')
            params["to_dt"] = to_dt

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = (
            f'SELECT * FROM "audit_log" {where_clause} '
            f'ORDER BY "ts" DESC LIMIT :limit OFFSET :offset'
        )
        rows = self._adapter.query(sql, params)
        return [AuditEntry.model_validate(row) for row in rows]

    # =========================================================================
    # Ресурсы
    # =========================================================================

    def close(self) -> None:
        """Освободить ресурсы SQLAlchemy engine."""
        self._adapter.dispose()
