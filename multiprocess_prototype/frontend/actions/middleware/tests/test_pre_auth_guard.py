"""Тесты PreAuthGuard — блокировка WriteAction до авторизации."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)
from multiprocess_prototype.frontend.actions.middleware.pre_auth_guard import (
    WRITE_ACTION_TYPES,
    PreAuthGuard,
)
from multiprocess_prototype.frontend.state.auth_state import AuthState


def _make_action(action_type: str = "field_set", undoable: bool = True) -> Action:
    return Action(
        action_type=action_type,
        forward_patch={"value": 1},
        backward_patch={"value": 0},
        undoable=undoable,
    )


@pytest.fixture
def auth_state(qtbot):
    """AuthState (QObject, требует QApplication через qtbot)."""
    return AuthState()


@pytest.fixture
def guard(auth_state):
    """PreAuthGuard с auth_state."""
    return PreAuthGuard(auth_state)


class TestPreAuthGuardHook:
    """Тесты hook()."""

    def test_blocks_write_when_not_authenticated(self, guard, auth_state):
        """Write action блокируется без авторизации."""
        assert auth_state.is_authenticated is False
        action = _make_action("field_set")
        assert guard.hook(action) is False

    def test_blocks_all_write_action_types(self, guard, auth_state):
        """Все WRITE_ACTION_TYPES блокируются без авторизации."""
        assert auth_state.is_authenticated is False
        for atype in WRITE_ACTION_TYPES:
            action = _make_action(atype, undoable=True)
            assert guard.hook(action) is False, f"{atype} должен быть заблокирован"

    def test_blocks_undoable_action_not_in_write_types(self, guard, auth_state):
        """Undoable action неизвестного типа тоже блокируется (undoable=True)."""
        assert auth_state.is_authenticated is False
        action = _make_action("custom_undoable", undoable=True)
        assert guard.hook(action) is False

    def test_allows_read_only_action(self, guard, auth_state):
        """Read-only action (node_move, undoable=False) проходит без авторизации."""
        assert auth_state.is_authenticated is False
        action = _make_action("node_move", undoable=False)
        assert guard.hook(action) is True

    def test_allows_non_undoable_non_write_action(self, guard, auth_state):
        """Non-undoable action не из WRITE_ACTION_TYPES проходит."""
        assert auth_state.is_authenticated is False
        action = _make_action("navigation", undoable=False)
        assert guard.hook(action) is True

    def test_allows_write_when_authenticated(self, guard, auth_state):
        """После авторизации все действия проходят."""
        ctx = AccessContext(role_name="admin")
        auth_state.set_user({"username": "alice"}, ctx)
        assert auth_state.is_authenticated is True

        action = _make_action("field_set")
        assert guard.hook(action) is True

    def test_allows_all_types_when_authenticated(self, guard, auth_state):
        """После авторизации все WRITE_ACTION_TYPES проходят."""
        ctx = AccessContext(role_name="operator")
        auth_state.set_user({"username": "bob"}, ctx)

        for atype in WRITE_ACTION_TYPES:
            action = _make_action(atype, undoable=True)
            assert guard.hook(action) is True, f"{atype} должен проходить после login"

    def test_blocks_after_logout(self, guard, auth_state):
        """После logout write actions снова блокируются."""
        ctx = AccessContext(role_name="admin")
        auth_state.set_user({"username": "alice"}, ctx)
        auth_state.clear()

        action = _make_action("field_set")
        assert guard.hook(action) is False


class TestPreAuthGuardOnBlocked:
    """Тесты on_blocked()."""

    def test_on_blocked_emits_action_blocked_signal(self, guard, auth_state, qtbot):
        """on_blocked эмитирует action_blocked сигнал на AuthState."""
        action = _make_action("field_set")
        action_model = action.model_copy(update={"description": "Установить значение"})

        with qtbot.waitSignal(auth_state.action_blocked, timeout=1000) as blocker:
            guard.on_blocked(action_model)

        assert "Установить значение" in blocker.args[0]

    def test_custom_on_blocked_callback(self, auth_state):
        """Custom callback вызывается вместо сигнала."""
        custom_cb = MagicMock()
        guard = PreAuthGuard(auth_state, on_blocked_callback=custom_cb)

        action = _make_action("field_set")
        guard.on_blocked(action)

        custom_cb.assert_called_once_with(action)


class TestActionBusIntegration:
    """Интеграция PreAuthGuard с ActionBus."""

    def test_bus_with_hook_blocks_before_login(self, auth_state, qtbot):
        """ActionBus с хуком: execute(write_action) до login — apply не вызывается."""
        rm = MagicMock()
        rm.set_field_value.return_value = (True, None)
        bus = ActionBus(rm, max_history=10)

        handler = MagicMock()
        handler.apply.return_value = None
        handler.revert.return_value = None
        bus.register_handler("field_set", handler)

        guard = PreAuthGuard(auth_state)
        bus.set_pre_execute_hook(guard.hook, on_blocked=guard.on_blocked)

        action = _make_action("field_set")
        bus.execute(action)

        handler.apply.assert_not_called()
        assert bus.can_undo() is False

    def test_bus_with_hook_allows_after_login(self, auth_state, qtbot):
        """ActionBus с хуком: execute после login — apply вызывается."""
        rm = MagicMock()
        rm.set_field_value.return_value = (True, None)
        bus = ActionBus(rm, max_history=10)

        handler = MagicMock()
        handler.apply.return_value = None
        handler.revert.return_value = None
        bus.register_handler("field_set", handler)

        guard = PreAuthGuard(auth_state)
        bus.set_pre_execute_hook(guard.hook, on_blocked=guard.on_blocked)

        # Login
        ctx = AccessContext(role_name="admin")
        auth_state.set_user({"username": "alice"}, ctx)

        action = _make_action("field_set")
        bus.execute(action)

        handler.apply.assert_called_once()
        assert bus.can_undo() is True
