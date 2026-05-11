# -*- coding: utf-8 -*-
"""
E2E smoke-тест PR4 — Audit Trail + SessionTracker + AuditWriter без Qt.

Сценарии:
1. login → open_session → log(AuditEntry) → list_audit → запись есть.
2. logout → close_session → logout_at проставлен.
3. AuditWriter с broken storage → JSONL существует → recover_fallback() → записи в БД.

Все тесты используют sqlite:///:memory: и tmp_path.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from Services.auth import (
    AuthConfig,
    AuthManager,
    BcryptHasher,
    LockoutPolicy,
    PasswordPolicy,
    Role,
    User,
    YamlUserStorage,
)
from Services.auth.audit_writer import AuditWriter
from Services.auth.models import AuditEntry, SessionEntry
from Services.auth.session_tracker import SessionTracker
from Services.auth.storage.audit_storage import SqliteAuditStorage


# =============================================================================
# Вспомогательные фабрики
# =============================================================================


def _make_sqlite_storage() -> SqliteAuditStorage:
    """in-memory SQLite хранилище со схемой."""
    storage = SqliteAuditStorage("sqlite:///:memory:")
    storage.ensure_schema()
    return storage


def _make_config(tmp_path: Path) -> AuthConfig:
    return AuthConfig(
        users_path=str(tmp_path / "users.yaml"),
        bcrypt_rounds=4,
        password_policy=PasswordPolicy(
            min_length=8,
            require_classes=3,
            bcrypt_rounds_prod=4,
            bcrypt_rounds_test=4,
        ),
        lockout_policy=LockoutPolicy(
            failed_threshold=5,
            reset_after_sec=1800,
            delays_sec=[30, 60, 120, 240, 480],
        ),
    )


def _seed_storage(users_path: str) -> None:
    """Заполнить YAML-хранилище: роль admin + пользователь alice."""
    storage = YamlUserStorage(users_path)
    hasher = BcryptHasher(rounds=4)
    storage.save_roles({"admin": Role(name="admin", level=9, permissions=["*"])})
    storage.save({
        "alice": User(
            user_id="uid-alice",
            username="alice",
            password_hash=hasher.hash("MySecret@1"),
            role_name="admin",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_active=True,
        )
    })


def _make_audit_entry(action_type: str = "field_update") -> AuditEntry:
    return AuditEntry.with_truncation(
        entry_id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        user_id="uid-alice",
        username="alice",
        action_type=action_type,
        resource="test.resource",
    )


# =============================================================================
# Тест 1: login → open_session → log → list_audit
# =============================================================================


class TestLoginSessionAuditFlow:
    """E2E: login → session → audit entry → проверка в БД."""

    def test_login_creates_session_entry(self, tmp_path: Path) -> None:
        """login() создаёт SessionEntry в БД."""
        config = _make_config(tmp_path)
        _seed_storage(config.users_path)

        sqlite_storage = _make_sqlite_storage()
        tracker = SessionTracker(sqlite_storage)

        manager = AuthManager(config)
        manager.initialize()
        manager.set_session_tracker(tracker)

        ctx = manager.login("alice", "MySecret@1")
        assert ctx["username"] == "alice"

        sessions = sqlite_storage.list_sessions("uid-alice")
        assert len(sessions) == 1
        session = sessions[0]
        assert session.username == "alice"
        assert session.logout_at is None

    def test_logout_closes_session(self, tmp_path: Path) -> None:
        """logout() проставляет logout_at в SessionEntry."""
        config = _make_config(tmp_path)
        _seed_storage(config.users_path)

        sqlite_storage = _make_sqlite_storage()
        tracker = SessionTracker(sqlite_storage)

        manager = AuthManager(config)
        manager.initialize()
        manager.set_session_tracker(tracker)

        manager.login("alice", "MySecret@1")
        manager.logout()

        sessions = sqlite_storage.list_sessions("uid-alice")
        assert len(sessions) == 1
        assert sessions[0].logout_at is not None

    def test_audit_writer_logs_entry_to_storage(self, tmp_path: Path) -> None:
        """AuditWriter.log() сохраняет AuditEntry в SQLite после flush."""
        sqlite_storage = _make_sqlite_storage()
        fallback_path = str(tmp_path / "audit_fallback.jsonl")

        writer = AuditWriter(sqlite_storage, fallback_path)
        writer.start()

        entry = _make_audit_entry("field_update")
        writer.log(entry)

        # Ждём flush батча (100 мс таймаут + запас)
        time.sleep(0.3)
        writer.stop()

        results = sqlite_storage.list_audit(
            user_id="uid-alice",
            resource=None,
            from_dt=None,
            to_dt=None,
        )
        assert len(results) == 1
        assert results[0].entry_id == entry.entry_id
        assert results[0].action_type == "field_update"


# =============================================================================
# Тест 2: AuditWriter broken storage → JSONL fallback → recover_fallback
# =============================================================================


class TestAuditWriterFallbackRecovery:
    """E2E: сбой SQLite → JSONL → recover_fallback → записи в БД."""

    def test_broken_storage_writes_jsonl_fallback(self, tmp_path: Path) -> None:
        """При сбое append_audit запись попадает в JSONL fallback."""
        sqlite_storage = _make_sqlite_storage()
        fallback_path = str(tmp_path / "audit_fallback.jsonl")

        # Ломаем storage
        original_append = sqlite_storage.append_audit
        sqlite_storage.append_audit = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("simulated SQLite failure")
        )

        writer = AuditWriter(sqlite_storage, fallback_path)
        writer.start()

        entry = _make_audit_entry("role_update")
        writer.log(entry)

        time.sleep(0.3)
        writer.stop()

        # JSONL должен существовать
        assert Path(fallback_path).exists(), "JSONL fallback должен быть создан"
        lines = Path(fallback_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1, "В JSONL должна быть хотя бы одна запись"

        # Проверяем что запись в JSONL соответствует нашей
        data = json.loads(lines[0])
        assert data["entry_id"] == entry.entry_id

    def test_recover_fallback_migrates_to_storage(self, tmp_path: Path) -> None:
        """recover_fallback() мигрирует JSONL записи в SQLite и архивирует файл."""
        sqlite_storage = _make_sqlite_storage()
        fallback_path = str(tmp_path / "audit_fallback.jsonl")

        # Шаг 1: Пишем напрямую в JSONL (имитируем fallback)
        entries = [_make_audit_entry(f"action_{i}") for i in range(3)]
        with open(fallback_path, "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(e.model_dump_json() + "\n")

        # Шаг 2: recover_fallback с рабочим storage
        writer = AuditWriter(sqlite_storage, fallback_path)
        recovered = writer.recover_fallback()

        assert recovered == 3, f"ожидали 3 восстановленные записи, got: {recovered}"

        # Проверяем что файл архивирован (переименован)
        assert not Path(fallback_path).exists(), "fallback файл должен быть архивирован"

        # Проверяем что записи в БД
        results = sqlite_storage.list_audit(
            user_id="uid-alice",
            resource=None,
            from_dt=None,
            to_dt=None,
        )
        assert len(results) == 3
        entry_ids = {r.entry_id for r in results}
        assert entry_ids == {e.entry_id for e in entries}

    def test_full_flow_broken_then_recovered(self, tmp_path: Path) -> None:
        """
        Полный E2E: writer с broken storage → JSONL → восстановление storage
        → recover_fallback → все записи в БД.
        """
        sqlite_storage = _make_sqlite_storage()
        fallback_path = str(tmp_path / "audit_fallback.jsonl")

        # --- Фаза 1: storage сломан ---
        original_append = sqlite_storage.append_audit
        fail_mock = MagicMock(side_effect=RuntimeError("disk full"))
        sqlite_storage.append_audit = fail_mock  # type: ignore[method-assign]

        writer = AuditWriter(sqlite_storage, fallback_path)
        writer.start()

        entries = [_make_audit_entry(f"event_{i}") for i in range(5)]
        for e in entries:
            writer.log(e)

        time.sleep(0.4)
        writer.stop()

        assert Path(fallback_path).exists(), "JSONL должен существовать"

        # --- Фаза 2: восстанавливаем storage ---
        sqlite_storage.append_audit = original_append  # type: ignore[method-assign]

        writer2 = AuditWriter(sqlite_storage, fallback_path)
        # recover_fallback вызывается внутри start()
        writer2.start()
        writer2.stop()

        # Файл должен быть архивирован
        assert not Path(fallback_path).exists(), "fallback должен быть архивирован"

        # Все 5 записей в БД
        results = sqlite_storage.list_audit(
            user_id="uid-alice",
            resource=None,
            from_dt=None,
            to_dt=None,
        )
        assert len(results) == 5


# =============================================================================
# Тест 3: Полный E2E с AuthManager + SessionTracker + AuditWriter
# =============================================================================


class TestFullPR4Integration:
    """Полный E2E: AuthManager + SessionTracker + AuditWriter из DI."""

    def test_di_assembly_and_flow(self, tmp_path: Path) -> None:
        """
        Собираем все компоненты через DI и прогоняем login → audit → logout.
        """
        config = _make_config(tmp_path)
        _seed_storage(config.users_path)

        # Сборка компонентов
        sqlite_storage = _make_sqlite_storage()
        fallback_path = str(tmp_path / "audit_fallback.jsonl")

        writer = AuditWriter(sqlite_storage, fallback_path)
        writer.start()

        tracker = SessionTracker(sqlite_storage)

        manager = AuthManager(config)
        manager.initialize()
        manager.set_audit_writer(writer)
        manager.set_session_tracker(tracker)

        # --- Login ---
        ctx = manager.login("alice", "MySecret@1")
        assert ctx["username"] == "alice"

        # Вручную логируем действие (как AuditMiddleware)
        entry = AuditEntry.with_truncation(
            entry_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            user_id=ctx["user_id"],
            username=ctx["username"],
            action_type="field_update",
            resource="recipe.threshold",
            before_json='{"threshold": 0.5}',
            after_json='{"threshold": 0.8}',
        )
        writer.log(entry)

        time.sleep(0.3)

        # --- Logout ---
        manager.logout()

        writer.stop()

        # Проверка сессии
        sessions = sqlite_storage.list_sessions("uid-alice")
        assert len(sessions) == 1
        assert sessions[0].logout_at is not None

        # Проверка audit entry
        audit_entries = sqlite_storage.list_audit(
            user_id="uid-alice",
            resource=None,
            from_dt=None,
            to_dt=None,
        )
        assert len(audit_entries) == 1
        assert audit_entries[0].action_type == "field_update"
        assert audit_entries[0].resource == "recipe.threshold"
