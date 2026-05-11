# -*- coding: utf-8 -*-
"""
Тесты AuditMiddleware — post-execute callback для ActionBus.

Без Qt-зависимостей: тесты чисто unit-уровня.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_prototype.frontend.actions.middleware.audit_middleware import AuditMiddleware
from Services.auth.models import AuditEntry


# =============================================================================
# Вспомогательные фабрики
# =============================================================================


def _make_action(
    action_type: str = "field_update",
    register_name: str | None = "processing",
    field_name: str | None = "threshold",
    forward_patch: dict | None = None,
    backward_patch: dict | None = None,
) -> Action:
    """Создать тестовый Action."""
    return Action(
        action_id=str(uuid.uuid4()),
        action_type=action_type,
        register_name=register_name,
        field_name=field_name,
        forward_patch=forward_patch or {"value": 42},
        backward_patch=backward_patch or {"value": 10},
    )


class _FakeStateStore:
    """Fake StateStore для тестов."""

    def __init__(self, current_user: Any = None) -> None:
        self._data = {"auth/current_user": current_user}

    def get(self, key: str) -> Any:
        return self._data.get(key)


# =============================================================================
# Тесты
# =============================================================================


def test_middleware_logs_action() -> None:
    """Авторизованный пользователь + action → AuditEntry.log() вызывается 1 раз."""
    mock_writer = MagicMock()
    state_store = _FakeStateStore(
        current_user={"user_id": "uid-alice", "username": "alice"}
    )

    middleware = AuditMiddleware(mock_writer, state_store)
    action = _make_action()

    middleware(action)

    # writer.log вызван ровно 1 раз
    assert mock_writer.log.call_count == 1

    # Переданный аргумент — AuditEntry
    logged_entry: AuditEntry = mock_writer.log.call_args[0][0]
    assert isinstance(logged_entry, AuditEntry)
    assert logged_entry.user_id == "uid-alice"
    assert logged_entry.username == "alice"
    assert logged_entry.action_type == action.action_type
    # resource: register_name приоритетнее field_name
    assert logged_entry.resource == action.register_name


def test_middleware_skips_no_user() -> None:
    """Нет авторизованного пользователя → writer.log НЕ вызывается."""
    mock_writer = MagicMock()
    state_store = _FakeStateStore(current_user=None)

    middleware = AuditMiddleware(mock_writer, state_store)
    action = _make_action()

    middleware(action)

    mock_writer.log.assert_not_called()


def test_middleware_uses_action_resource_when_present() -> None:
    """action.resource задан → entry.resource == action.resource (игнорирует register_name)."""
    mock_writer = MagicMock()
    state_store = _FakeStateStore(
        current_user={"user_id": "uid-bob", "username": "bob"}
    )

    middleware = AuditMiddleware(mock_writer, state_store)

    # Action с явным resource (как у V2ActionBuilder.role_update)
    action = Action(
        action_id=str(uuid.uuid4()),
        action_type="role_update",
        register_name="some_register",  # должен быть проигнорирован
        field_name="some_field",        # должен быть проигнорирован
        resource="roles.admin",         # именно это должно попасть в entry
        forward_patch={"permissions": ["roles.view"]},
        backward_patch={"permissions": []},
    )

    middleware(action)

    assert mock_writer.log.call_count == 1
    logged_entry: AuditEntry = mock_writer.log.call_args[0][0]
    assert logged_entry.resource == "roles.admin"


def test_middleware_falls_back_to_register_name() -> None:
    """action.resource отсутствует → entry.resource == action.register_name (fallback)."""
    mock_writer = MagicMock()
    state_store = _FakeStateStore(
        current_user={"user_id": "uid-carol", "username": "carol"}
    )

    middleware = AuditMiddleware(mock_writer, state_store)

    # Action без resource — классический field_update
    action = Action(
        action_id=str(uuid.uuid4()),
        action_type="field_update",
        register_name="some_reg",
        field_name="threshold",
        # resource не задан (None по умолчанию)
        forward_patch={"value": 99},
        backward_patch={"value": 1},
    )

    middleware(action)

    assert mock_writer.log.call_count == 1
    logged_entry: AuditEntry = mock_writer.log.call_args[0][0]
    assert logged_entry.resource == "some_reg"
