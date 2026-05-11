# -*- coding: utf-8 -*-
"""
Тесты для SqliteAuditStorage (Group A, PR4).

Все тесты используют in-memory SQLite (``sqlite:///:memory:``).

Покрываемые сценарии:
    test_append_audit_and_list         — insert + фильтрация по user_id и датам.
    test_audit_immutable_update        — попытка update → AuditImmutableError.
    test_audit_immutable_delete        — попытка delete → AuditImmutableError.
    test_session_open_close            — insert SessionEntry + update logout_at.
    test_list_sessions_by_user         — фильтр list_sessions по user_id.
    test_ensure_schema_idempotent      — двойной вызов ensure_schema без ошибок.
    test_truncation                    — before_json > 10 KB усекается с суффиксом.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from Services.auth.exceptions import AuditImmutableError
from Services.auth.models import AuditEntry, SessionEntry, _JSON_MAX_BYTES, _TRUNCATED_SUFFIX
from Services.auth.storage.audit_storage import SqliteAuditStorage


# =============================================================================
# Фикстуры
# =============================================================================


@pytest.fixture()
def storage() -> SqliteAuditStorage:
    """In-memory SQLiteAuditStorage с созданной схемой."""
    s = SqliteAuditStorage("sqlite:///:memory:")
    s.ensure_schema()
    return s


def _make_audit(
    user_id: str = "u1",
    username: str = "alice",
    action_type: str = "field_update",
    resource: str | None = "processing.threshold",
    ts: datetime | None = None,
    before_json: str | None = None,
    after_json: str | None = None,
) -> AuditEntry:
    """Вспомогательная фабрика AuditEntry для тестов."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    return AuditEntry.with_truncation(
        entry_id=str(uuid.uuid4()),
        ts=ts,
        user_id=user_id,
        username=username,
        action_type=action_type,
        resource=resource,
        before_json=before_json,
        after_json=after_json,
    )


def _make_session(
    user_id: str = "u1",
    username: str = "alice",
    login_at: datetime | None = None,
) -> SessionEntry:
    """Вспомогательная фабрика SessionEntry для тестов."""
    if login_at is None:
        login_at = datetime.now(timezone.utc)
    return SessionEntry(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        username=username,
        login_at=login_at,
        host="localhost",
    )


# =============================================================================
# Тесты
# =============================================================================


class TestAppendAuditAndList:
    """Тест: append_audit + list_audit с фильтрацией."""

    def test_append_audit_and_list(self, storage: SqliteAuditStorage) -> None:
        """Записанные события должны возвращаться через list_audit с фильтром по user_id."""
        now = datetime.now(timezone.utc)
        e1 = _make_audit(user_id="u1", ts=now)
        e2 = _make_audit(user_id="u2", ts=now)
        e3 = _make_audit(user_id="u1", ts=now - timedelta(seconds=5))

        storage.append_audit(e1)
        storage.append_audit(e2)
        storage.append_audit(e3)

        # Фильтр по user_id="u1" — должно вернуть e1 и e3
        results = storage.list_audit(user_id="u1")
        assert len(results) == 2
        ids = {r.entry_id for r in results}
        assert e1.entry_id in ids
        assert e3.entry_id in ids
        assert e2.entry_id not in ids

    def test_list_audit_with_date_filter(self, storage: SqliteAuditStorage) -> None:
        """Фильтрация по from_dt / to_dt должна возвращать правильное подмножество."""
        base_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        early = _make_audit(user_id="u1", ts=base_dt)
        mid = _make_audit(user_id="u1", ts=base_dt + timedelta(hours=1))
        late = _make_audit(user_id="u1", ts=base_dt + timedelta(hours=2))

        for e in [early, mid, late]:
            storage.append_audit(e)

        # from_dt <= mid <= to_dt → только mid
        results = storage.list_audit(
            from_dt=base_dt + timedelta(minutes=30),
            to_dt=base_dt + timedelta(minutes=90),
        )
        assert len(results) == 1
        assert results[0].entry_id == mid.entry_id

    def test_list_audit_limit_offset(self, storage: SqliteAuditStorage) -> None:
        """Пагинация через limit / offset должна работать корректно."""
        now = datetime.now(timezone.utc)
        entries = [_make_audit(user_id="u1", ts=now - timedelta(seconds=i)) for i in range(5)]
        for e in entries:
            storage.append_audit(e)

        page1 = storage.list_audit(limit=2, offset=0)
        page2 = storage.list_audit(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        # Страницы не должны пересекаться
        ids1 = {r.entry_id for r in page1}
        ids2 = {r.entry_id for r in page2}
        assert ids1.isdisjoint(ids2)


class TestAuditImmutable:
    """Тест: UPDATE и DELETE для AuditEntry запрещены."""

    def test_audit_immutable_update(self, storage: SqliteAuditStorage) -> None:
        """Попытка update через репозиторий должна выбрасывать AuditImmutableError."""
        entry = _make_audit()
        storage.append_audit(entry)

        with pytest.raises(AuditImmutableError) as exc_info:
            storage._audit.update(entry.entry_id, entry)

        assert exc_info.value.code == "AUTH-007"

    def test_audit_immutable_delete(self, storage: SqliteAuditStorage) -> None:
        """Попытка delete через репозиторий должна выбрасывать AuditImmutableError."""
        entry = _make_audit()
        storage.append_audit(entry)

        with pytest.raises(AuditImmutableError) as exc_info:
            storage._audit.delete(entry.entry_id)

        assert exc_info.value.code == "AUTH-007"


class TestSessionOpenClose:
    """Тест: открытие и закрытие сессии."""

    def test_session_open_close(self, storage: SqliteAuditStorage) -> None:
        """append_session + close_session должны корректно проставлять logout_at."""
        login_dt = datetime.now(timezone.utc)
        session = _make_session(login_at=login_dt)
        storage.append_session(session)

        # Проверяем что сессия записана
        sessions = storage.list_sessions(user_id="u1")
        assert len(sessions) == 1
        assert sessions[0].logout_at is None

        # Закрываем сессию
        logout_dt = login_dt + timedelta(minutes=15)
        storage.close_session(session.session_id, logout_dt)

        # Проверяем что logout_at проставлен
        sessions_after = storage.list_sessions(user_id="u1")
        assert len(sessions_after) == 1
        assert sessions_after[0].logout_at is not None

    def test_close_nonexistent_session(self, storage: SqliteAuditStorage) -> None:
        """close_session для несуществующей сессии должна быть no-op (не падать)."""
        storage.close_session("nonexistent-id", datetime.now(timezone.utc))


class TestListSessionsByUser:
    """Тест: list_sessions с фильтром по user_id."""

    def test_list_sessions_by_user(self, storage: SqliteAuditStorage) -> None:
        """list_sessions(user_id=...) должна возвращать только сессии нужного пользователя."""
        now = datetime.now(timezone.utc)
        s1 = _make_session(user_id="alice", login_at=now)
        s2 = _make_session(user_id="alice", login_at=now - timedelta(hours=1))
        s3 = _make_session(user_id="bob", login_at=now)

        for s in [s1, s2, s3]:
            storage.append_session(s)

        alice_sessions = storage.list_sessions(user_id="alice")
        assert len(alice_sessions) == 2
        assert all(s.user_id == "alice" for s in alice_sessions)

        bob_sessions = storage.list_sessions(user_id="bob")
        assert len(bob_sessions) == 1
        assert bob_sessions[0].user_id == "bob"

    def test_list_sessions_all_users(self, storage: SqliteAuditStorage) -> None:
        """list_sessions() без фильтра должна возвращать сессии всех пользователей."""
        for user_id in ["alice", "bob", "charlie"]:
            storage.append_session(_make_session(user_id=user_id))

        all_sessions = storage.list_sessions()
        assert len(all_sessions) == 3


class TestEnsureSchemaIdempotent:
    """Тест: ensure_schema() идемпотентна."""

    def test_ensure_schema_idempotent(self) -> None:
        """Двойной вызов ensure_schema не должен поднимать исключений."""
        s = SqliteAuditStorage("sqlite:///:memory:")
        s.ensure_schema()
        # Второй вызов — должен пройти без ошибок
        s.ensure_schema()
        # Проверяем что данные после повторного вызова не потерялись
        entry = _make_audit()
        s.append_audit(entry)
        results = s.list_audit()
        assert len(results) == 1

    def test_ensure_schema_preserves_data(self) -> None:
        """Вызов ensure_schema после записи данных не должен удалять их."""
        s = SqliteAuditStorage("sqlite:///:memory:")
        s.ensure_schema()
        entry = _make_audit()
        s.append_audit(entry)
        # Повторный вызов ensure_schema
        s.ensure_schema()
        # Данные должны быть на месте
        results = s.list_audit()
        assert len(results) == 1
        assert results[0].entry_id == entry.entry_id


class TestTruncation:
    """Тест: усечение before_json / after_json при превышении 10 КБ."""

    def test_truncation_large_before_json(self, storage: SqliteAuditStorage) -> None:
        """before_json > 10 KB должен усекаться с суффиксом '<truncated>'."""
        # Создаём строку > 10 КБ
        large_value = "x" * (_JSON_MAX_BYTES + 100)
        assert len(large_value.encode("utf-8")) > _JSON_MAX_BYTES

        entry = AuditEntry.with_truncation(
            entry_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            user_id="u1",
            username="alice",
            action_type="field_update",
            before_json=large_value,
            after_json=None,
        )

        # Проверяем что перед сохранением поле уже усечено
        assert entry.before_json is not None
        assert entry.before_json.endswith(_TRUNCATED_SUFFIX)
        assert len(entry.before_json.encode("utf-8")) <= _JSON_MAX_BYTES + len(_TRUNCATED_SUFFIX)

        # Сохраняем и читаем обратно
        storage.append_audit(entry)
        results = storage.list_audit(user_id="u1")
        assert len(results) == 1
        assert results[0].before_json is not None
        assert results[0].before_json.endswith(_TRUNCATED_SUFFIX)

    def test_truncation_small_json_unchanged(self) -> None:
        """before_json меньше 10 KB не должен усекаться."""
        small_value = '{"key": "value"}'
        entry = AuditEntry.with_truncation(
            entry_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            user_id="u1",
            username="alice",
            action_type="field_update",
            before_json=small_value,
        )
        assert entry.before_json == small_value

    def test_truncation_none_passes_through(self) -> None:
        """None для before_json / after_json должен передаваться без изменений."""
        entry = AuditEntry.with_truncation(
            entry_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            user_id="u1",
            username="alice",
            action_type="field_update",
            before_json=None,
            after_json=None,
        )
        assert entry.before_json is None
        assert entry.after_json is None

    def test_truncation_large_after_json(self) -> None:
        """after_json > 10 KB тоже должен усекаться с суффиксом."""
        large_value = "y" * (_JSON_MAX_BYTES + 500)
        entry = AuditEntry.with_truncation(
            entry_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            user_id="u1",
            username="alice",
            action_type="field_update",
            after_json=large_value,
        )
        assert entry.after_json is not None
        assert entry.after_json.endswith(_TRUNCATED_SUFFIX)


class TestSerializationRoundtrip:
    """Тест: сериализация и десериализация SessionEntry / AuditEntry."""

    def test_session_entry_roundtrip(self) -> None:
        """SessionEntry.to_dict() / model_validate() должны работать без потерь."""
        session = _make_session()
        data = session.model_dump()
        restored = SessionEntry.model_validate(data)
        assert restored.session_id == session.session_id
        assert restored.user_id == session.user_id
        assert restored.logout_at == session.logout_at

    def test_audit_entry_roundtrip(self) -> None:
        """AuditEntry.model_dump() / model_validate() должны работать без потерь."""
        entry = _make_audit()
        data = entry.model_dump()
        restored = AuditEntry.model_validate(data)
        assert restored.entry_id == entry.entry_id
        assert restored.action_type == entry.action_type
        assert restored.resource == entry.resource
