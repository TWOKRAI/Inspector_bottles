"""Тесты AuthState — реактивное состояние авторизации."""
from __future__ import annotations

import pytest

from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)
from multiprocess_prototype.frontend.state.auth_state import (
    AuthState,
    wire_auth_state_to_window_manager,
)


@pytest.fixture
def auth_state(qtbot):
    """AuthState с QApplication (через qtbot)."""
    state = AuthState()
    return state


class TestAuthStateInitial:
    """Начальное состояние AuthState."""

    def test_initial_not_authenticated(self, auth_state):
        assert auth_state.is_authenticated is False

    def test_initial_current_user_is_none(self, auth_state):
        assert auth_state.current_user is None

    def test_initial_access_context_default(self, auth_state):
        assert auth_state.access_context == AccessContext()
        assert auth_state.access_context.level == 0
        assert auth_state.access_context.role_name == ""
        assert auth_state.access_context.permissions == frozenset()


class TestAuthStateSetUser:
    """Тесты set_user."""

    def test_set_user_updates_state(self, auth_state):
        user = {"username": "alice", "role_name": "admin"}
        ctx = AccessContext(level=9, role_name="admin", permissions=frozenset({"tabs.recipes.view"}))
        auth_state.set_user(user, ctx)

        assert auth_state.is_authenticated is True
        assert auth_state.current_user["username"] == "alice"
        assert auth_state.access_context.role_name == "admin"
        assert auth_state.access_context.level == 9

    def test_set_user_emits_current_user_changed(self, auth_state, qtbot):
        user = {"username": "alice"}
        ctx = AccessContext(role_name="admin")

        with qtbot.waitSignal(auth_state.current_user_changed, timeout=1000) as blocker:
            auth_state.set_user(user, ctx)

        assert blocker.args[0] == user

    def test_set_user_emits_access_context_changed(self, auth_state, qtbot):
        user = {"username": "alice"}
        ctx = AccessContext(role_name="admin", permissions=frozenset({"p1"}))

        with qtbot.waitSignal(auth_state.access_context_changed, timeout=1000) as blocker:
            auth_state.set_user(user, ctx)

        # Сигнал эмитирует строго AccessContext, не dict
        emitted_ctx = blocker.args[0]
        assert isinstance(emitted_ctx, AccessContext)
        assert emitted_ctx.role_name == "admin"

    def test_set_user_emits_both_signals(self, auth_state, qtbot):
        """Оба сигнала эмитируются при set_user."""
        user = {"username": "bob"}
        ctx = AccessContext(role_name="operator")

        signals_received = []

        auth_state.current_user_changed.connect(lambda u: signals_received.append("user"))
        auth_state.access_context_changed.connect(lambda c: signals_received.append("ctx"))

        auth_state.set_user(user, ctx)

        assert "user" in signals_received
        assert "ctx" in signals_received


class TestAuthStateClear:
    """Тесты clear."""

    def test_clear_resets_state(self, auth_state):
        user = {"username": "alice"}
        ctx = AccessContext(role_name="admin")
        auth_state.set_user(user, ctx)

        auth_state.clear()

        assert auth_state.is_authenticated is False
        assert auth_state.current_user is None
        assert auth_state.access_context == AccessContext()

    def test_clear_emits_current_user_changed(self, auth_state, qtbot):
        user = {"username": "alice"}
        ctx = AccessContext(role_name="admin")
        auth_state.set_user(user, ctx)

        with qtbot.waitSignal(auth_state.current_user_changed, timeout=1000) as blocker:
            auth_state.clear()

        assert blocker.args[0] is None

    def test_clear_emits_access_context_changed(self, auth_state, qtbot):
        user = {"username": "alice"}
        ctx = AccessContext(role_name="admin")
        auth_state.set_user(user, ctx)

        with qtbot.waitSignal(auth_state.access_context_changed, timeout=1000) as blocker:
            auth_state.clear()

        emitted_ctx = blocker.args[0]
        assert isinstance(emitted_ctx, AccessContext)
        assert emitted_ctx == AccessContext()

    def test_clear_emits_both_signals(self, auth_state, qtbot):
        user = {"username": "bob"}
        ctx = AccessContext(role_name="operator")
        auth_state.set_user(user, ctx)

        signals_received = []
        auth_state.current_user_changed.connect(lambda u: signals_received.append("user"))
        auth_state.access_context_changed.connect(lambda c: signals_received.append("ctx"))

        auth_state.clear()

        assert "user" in signals_received
        assert "ctx" in signals_received


class TestAuthStateAccessContext:
    """Тесты access_context после login."""

    def test_access_context_has_role_name(self, auth_state):
        ctx = AccessContext(role_name="admin", level=9)
        auth_state.set_user({"username": "alice"}, ctx)
        assert auth_state.access_context.role_name == "admin"

    def test_access_context_has_permissions(self, auth_state):
        perms = frozenset({"tabs.recipes.view", "tabs.recipes.edit"})
        ctx = AccessContext(role_name="admin", permissions=perms)
        auth_state.set_user({"username": "alice"}, ctx)
        assert auth_state.access_context.permissions == perms

    def test_access_context_from_dict(self, auth_state):
        """Типичный сценарий: AccessContext.from_dict от результата login()."""
        login_result = {
            "username": "alice",
            "role_name": "admin",
            "level": 9,
            "permissions": ["tabs.recipes.view", "tabs.recipes.edit"],
            "bypass_readonly": True,
            "show_hidden": True,
        }
        ctx = AccessContext.from_dict(login_result)
        auth_state.set_user(login_result, ctx)

        assert auth_state.access_context.role_name == "admin"
        assert auth_state.access_context.level == 9
        assert auth_state.access_context.bypass_readonly is True


class TestWireAuthStateToWindowManager:
    """Тесты forward-compat функции wire_auth_state_to_window_manager."""

    def test_function_exists_and_importable(self):
        """Функция импортируется без ошибок."""
        assert callable(wire_auth_state_to_window_manager)

    def test_wire_connects_signal(self, auth_state, qtbot):
        """Проверяем, что wire-up подключает сигнал к mock window_manager."""
        from unittest.mock import MagicMock

        mock_wm = MagicMock()
        wire_auth_state_to_window_manager(auth_state, mock_wm)

        ctx = AccessContext(role_name="admin")
        auth_state.set_user({"username": "alice"}, ctx)

        mock_wm.set_access_context.assert_called_once_with(ctx)
