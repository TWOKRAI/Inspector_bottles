"""Тесты set_pre_execute_hook — hook блокирует execute, не блокирует undo/redo."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action


def _make_action(
    action_type: str = "SET_VALUE",
    undoable: bool = True,
) -> Action:
    return Action(
        action_type=action_type,
        forward_patch={"value": 1},
        backward_patch={"value": 0},
        undoable=undoable,
    )


def _make_rm() -> MagicMock:
    rm = MagicMock()
    rm.set_field_value.return_value = (True, None)
    return rm


def _make_handler() -> MagicMock:
    handler = MagicMock()
    handler.apply.return_value = None
    handler.revert.return_value = None
    return handler


@pytest.fixture
def bus():
    """Фикстура: ActionBus с зарегистрированным handler."""
    rm = _make_rm()
    b = ActionBus(rm, max_history=10)
    handler = _make_handler()
    b.register_handler("SET_VALUE", handler)
    return b, handler, rm


class TestPreExecuteHook:
    """Тесты для set_pre_execute_hook."""

    def test_hook_blocks_execute(self, bus):
        """Hook возвращает False — handler.apply не вызывается."""
        b, handler, _rm = bus
        hook = MagicMock(return_value=False)
        b.set_pre_execute_hook(hook)

        action = _make_action()
        b.execute(action)

        hook.assert_called_once_with(action)
        handler.apply.assert_not_called()
        assert b.can_undo() is False

    def test_hook_allows_execute(self, bus):
        """Hook возвращает True — handler.apply вызывается нормально."""
        b, handler, rm = bus
        hook = MagicMock(return_value=True)
        b.set_pre_execute_hook(hook)

        action = _make_action()
        b.execute(action)

        hook.assert_called_once_with(action)
        handler.apply.assert_called_once_with(action, rm)
        assert b.can_undo() is True

    def test_on_blocked_called_when_hook_blocks(self, bus):
        """on_blocked вызывается при блокировке."""
        b, _handler, _rm = bus
        hook = MagicMock(return_value=False)
        on_blocked = MagicMock()
        b.set_pre_execute_hook(hook, on_blocked=on_blocked)

        action = _make_action()
        b.execute(action)

        on_blocked.assert_called_once_with(action)

    def test_on_blocked_not_called_when_allowed(self, bus):
        """on_blocked НЕ вызывается если hook разрешает."""
        b, _handler, _rm = bus
        hook = MagicMock(return_value=True)
        on_blocked = MagicMock()
        b.set_pre_execute_hook(hook, on_blocked=on_blocked)

        b.execute(_make_action())

        on_blocked.assert_not_called()

    def test_undo_bypasses_hook(self, bus):
        """undo() не проходит через pre-execute hook."""
        b, handler, _rm = bus
        # Сначала выполняем action без хука
        action = _make_action()
        b.execute(action)
        assert b.can_undo() is True

        # Ставим блокирующий хук
        hook = MagicMock(return_value=False)
        b.set_pre_execute_hook(hook)

        # undo должен пройти несмотря на блокирующий хук
        result = b.undo()
        assert result is not None
        handler.revert.assert_called_once()
        # hook не должен вызываться при undo
        hook.assert_not_called()

    def test_redo_bypasses_hook(self, bus):
        """redo() не проходит через pre-execute hook."""
        b, handler, _rm = bus
        # execute -> undo -> ставим хук -> redo
        action = _make_action()
        b.execute(action)
        b.undo()

        hook = MagicMock(return_value=False)
        b.set_pre_execute_hook(hook)

        # redo должен пройти несмотря на блокирующий хук
        result = b.redo()
        assert result is not None
        # handler.apply: 1 раз при execute + 1 раз при redo = 2
        assert handler.apply.call_count == 2
        # hook не должен вызываться при redo
        hook.assert_not_called()

    def test_callbacks_not_called_when_blocked(self, bus):
        """_notify_callbacks НЕ вызывается при блокировке (action ничего не изменил)."""
        b, _handler, _rm = bus
        hook = MagicMock(return_value=False)
        b.set_pre_execute_hook(hook)

        called = []
        b.add_change_callback(lambda: called.append(1))

        b.execute(_make_action())

        assert len(called) == 0

    def test_clear_pre_execute_hook(self, bus):
        """clear_pre_execute_hook сбрасывает хук."""
        b, handler, _rm = bus
        hook = MagicMock(return_value=False)
        b.set_pre_execute_hook(hook)

        b.clear_pre_execute_hook()

        action = _make_action()
        b.execute(action)

        # hook уже не вызывается, action проходит
        hook.assert_not_called()
        handler.apply.assert_called_once()

    def test_last_write_wins(self, bus):
        """Повторный set_pre_execute_hook заменяет предыдущий."""
        b, handler, _rm = bus
        hook1 = MagicMock(return_value=False)
        hook2 = MagicMock(return_value=True)

        b.set_pre_execute_hook(hook1)
        b.set_pre_execute_hook(hook2)

        b.execute(_make_action())

        hook1.assert_not_called()
        hook2.assert_called_once()
        handler.apply.assert_called_once()

    def test_command_action_also_checked_by_hook(self, bus):
        """Даже COMMAND (undoable=False) проходит через hook."""
        b, handler, _rm = bus
        b.register_handler("CMD", _make_handler())
        hook = MagicMock(return_value=False)
        b.set_pre_execute_hook(hook)

        action = _make_action("CMD", undoable=False)
        b.register_handler("CMD", handler)
        b.execute(action)

        hook.assert_called_once_with(action)
        handler.apply.assert_not_called()
