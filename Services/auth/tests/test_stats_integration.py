# -*- coding: utf-8 -*-
"""
Тесты StatsManager-интеграции — метрики auth.login.* и auth.sessions.active.

Проверяем, что _record_metric вызывается с правильными значениями при
каждом исходе login() и при open/close сессий.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import call, patch

import pytest

from Services.auth import (
    AccountLocked,
    AuthConfig,
    AuthManager,
    BcryptHasher,
    InvalidCredentials,
    LockoutPolicy,
    PasswordPolicy,
    Role,
    User,
    YamlUserStorage,
)
from Services.auth.session_tracker import SessionTracker
from Services.auth.storage.audit_storage import SqliteAuditStorage


# =============================================================================
# Вспомогательные фабрики
# =============================================================================


def _make_storage_sqlite() -> SqliteAuditStorage:
    """in-memory SQLite хранилище аудита."""
    storage = SqliteAuditStorage("sqlite:///:memory:")
    storage.ensure_schema()
    return storage


def _make_user(username: str, role_name: str = "admin") -> User:
    hasher = BcryptHasher(rounds=4)
    return User(
        user_id=f"uid-{username}",
        username=username,
        password_hash=hasher.hash("ValidPass@1"),
        role_name=role_name,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_active=True,
    )


def _make_role(name: str, level: int = 1) -> Role:
    return Role(name=name, level=level, permissions=["tabs.view"])


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
            failed_threshold=10,
            reset_after_sec=1800,
            delays_sec=[30, 60, 120, 240, 480],
        ),
    )


def _seed(users_path: str) -> None:
    """Создать хранилище с пользователем alice и ролью admin."""
    storage = YamlUserStorage(users_path)
    storage.save_roles({
        "admin": _make_role("admin", level=9),
    })
    storage.save({"alice": _make_user("alice", "admin")})


# =============================================================================
# Тесты login-attempts и failed_ratio
# =============================================================================


class TestLoginAttemptMetrics:
    """Тесты метрик auth.login.attempts.per_hour и auth.login.failed_ratio."""

    def test_attempts_increments_on_login(self, tmp_path: Path) -> None:
        """После 3 login (2 fail + 1 success): attempts=3, failed_ratio≈0.67."""
        config = _make_config(tmp_path)
        _seed(config.users_path)
        manager = AuthManager(config)
        manager.initialize()

        # Захватываем вызовы _record_metric
        recorded_metrics: list[tuple[str, object]] = []

        original_record = manager._record_metric

        def capture(name: str, value: object, *args, **kwargs) -> None:
            recorded_metrics.append((name, value))
            original_record(name, value, *args, **kwargs)

        manager._record_metric = capture  # type: ignore[method-assign]

        # Попытка 1 — неверный пароль
        with pytest.raises(InvalidCredentials):
            manager.login("alice", "WrongPass@99")

        # Попытка 2 — неверный пароль
        with pytest.raises(InvalidCredentials):
            manager.login("alice", "WrongPass@99")

        # Попытка 3 — успешная
        manager.login("alice", "ValidPass@1")

        # Собираем финальные значения метрик
        attempts_values = [v for n, v in recorded_metrics if n == "auth.login.attempts.per_hour"]
        ratio_values = [v for n, v in recorded_metrics if n == "auth.login.failed_ratio"]

        # Должны быть 3 вызова каждой метрики (по одному на попытку)
        assert len(attempts_values) == 3, f"ожидали 3 записи attempts, got: {attempts_values}"
        assert len(ratio_values) == 3, f"ожидали 3 записи ratio, got: {ratio_values}"

        # Финальные значения: после 3 попыток (2 fail + 1 success)
        assert attempts_values[-1] == 3, f"ожидали attempts=3, got: {attempts_values[-1]}"
        final_ratio = ratio_values[-1]
        assert isinstance(final_ratio, float)
        assert abs(final_ratio - 2 / 3) < 1e-6, f"ожидали ratio≈0.667, got: {final_ratio}"

    def test_success_only_ratio_zero(self, tmp_path: Path) -> None:
        """После 1 успешного входа: attempts=1, failed_ratio=0.0."""
        config = _make_config(tmp_path)
        _seed(config.users_path)
        manager = AuthManager(config)
        manager.initialize()

        recorded: list[tuple[str, object]] = []
        original = manager._record_metric

        def capture(name: str, value: object, *args, **kwargs) -> None:
            recorded.append((name, value))
            original(name, value, *args, **kwargs)

        manager._record_metric = capture  # type: ignore[method-assign]

        manager.login("alice", "ValidPass@1")

        attempts = [v for n, v in recorded if n == "auth.login.attempts.per_hour"]
        ratios = [v for n, v in recorded if n == "auth.login.failed_ratio"]

        assert attempts[-1] == 1
        assert ratios[-1] == 0.0

    def test_failed_only_ratio_one(self, tmp_path: Path) -> None:
        """После 2 неудачных входов: attempts=2, failed_ratio=1.0."""
        config = _make_config(tmp_path)
        _seed(config.users_path)
        manager = AuthManager(config)
        manager.initialize()

        recorded: list[tuple[str, object]] = []
        original = manager._record_metric

        def capture(name: str, value: object, *args, **kwargs) -> None:
            recorded.append((name, value))
            original(name, value, *args, **kwargs)

        manager._record_metric = capture  # type: ignore[method-assign]

        with pytest.raises(InvalidCredentials):
            manager.login("alice", "bad@1")
        with pytest.raises(InvalidCredentials):
            manager.login("alice", "bad@1")

        attempts = [v for n, v in recorded if n == "auth.login.attempts.per_hour"]
        ratios = [v for n, v in recorded if n == "auth.login.failed_ratio"]

        assert attempts[-1] == 2
        assert ratios[-1] == 1.0

    def test_locked_account_records_attempt(self, tmp_path: Path) -> None:
        """AccountLocked тоже записывает попытку как failed."""
        config = AuthConfig(
            users_path=str(tmp_path / "users.yaml"),
            bcrypt_rounds=4,
            password_policy=PasswordPolicy(
                min_length=8,
                require_classes=3,
                bcrypt_rounds_prod=4,
                bcrypt_rounds_test=4,
            ),
            lockout_policy=LockoutPolicy(
                failed_threshold=2,
                reset_after_sec=3600,
                delays_sec=[999, 999],
            ),
        )
        _seed(config.users_path)
        manager = AuthManager(config)
        manager.initialize()

        recorded: list[tuple[str, object]] = []
        original = manager._record_metric

        def capture(name: str, value: object, *args, **kwargs) -> None:
            recorded.append((name, value))
            original(name, value, *args, **kwargs)

        manager._record_metric = capture  # type: ignore[method-assign]

        # 2 неудачных → блокировка
        with pytest.raises(InvalidCredentials):
            manager.login("alice", "bad@1")
        with pytest.raises(InvalidCredentials):
            manager.login("alice", "bad@1")

        # 3-я попытка — AccountLocked
        with pytest.raises(AccountLocked):
            manager.login("alice", "bad@1")

        attempts = [v for n, v in recorded if n == "auth.login.attempts.per_hour"]
        # Должно быть 3 записи — все три попытки
        assert len(attempts) == 3
        assert attempts[-1] == 3


# =============================================================================
# Тесты auth.sessions.active
# =============================================================================


class TestActiveSessionsMetric:
    """Тесты метрики auth.sessions.active через SessionTracker callback."""

    def test_active_sessions_counter(self) -> None:
        """open×3 → active=3; close×1 → active=2."""
        storage = _make_storage_sqlite()
        active_values: list[int] = []
        tracker = SessionTracker(storage, on_active_change=active_values.append)

        # Открываем 3 сессии
        sid1 = tracker.open_session("uid-001", "alice")
        sid2 = tracker.open_session("uid-002", "bob")
        sid3 = tracker.open_session("uid-003", "carol")

        assert active_values == [1, 2, 3], f"after 3 opens: {active_values}"
        assert tracker._active_sessions_count == 3

        # Закрываем одну
        tracker.close_session(sid1)

        assert active_values[-1] == 2, f"after close: {active_values[-1]}"
        assert tracker._active_sessions_count == 2

    def test_active_sessions_no_negative(self) -> None:
        """Счётчик не уходит ниже нуля при лишнем close."""
        storage = _make_storage_sqlite()
        active_values: list[int] = []
        tracker = SessionTracker(storage, on_active_change=active_values.append)

        sid = tracker.open_session("uid-001", "alice")
        tracker.close_session(sid)
        # Повторный close с тем же session_id — счётчик уже 0, не должен стать -1
        tracker.close_session(sid)

        assert all(v >= 0 for v in active_values), f"отрицательный счётчик: {active_values}"
        assert tracker._active_sessions_count == 0

    def test_active_callback_via_auth_manager(self, tmp_path: Path) -> None:
        """set_session_tracker подключает callback → метрика публикуется через manager."""
        config = _make_config(tmp_path)
        _seed(config.users_path)
        manager = AuthManager(config)
        manager.initialize()

        sqlite_storage = _make_storage_sqlite()
        tracker = SessionTracker(sqlite_storage)

        # Перехватываем _record_metric
        recorded: list[tuple[str, object]] = []
        original = manager._record_metric

        def capture(name: str, value: object, *args, **kwargs) -> None:
            recorded.append((name, value))
            original(name, value, *args, **kwargs)

        manager._record_metric = capture  # type: ignore[method-assign]

        # Инжектируем tracker — должен подключить callback
        manager.set_session_tracker(tracker)

        # Логинимся (open_session вызывается внутри login)
        manager.login("alice", "ValidPass@1")

        session_metrics = [v for n, v in recorded if n == "auth.sessions.active"]
        assert len(session_metrics) >= 1, "метрика auth.sessions.active должна быть записана"
        assert session_metrics[-1] == 1

        # Логаут
        manager.logout()
        session_metrics_after = [v for n, v in recorded if n == "auth.sessions.active"]
        assert session_metrics_after[-1] == 0
