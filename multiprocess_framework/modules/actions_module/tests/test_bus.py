"""Тесты ActionBus — шина действий с undo/redo и coalescing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.actions_module.bus import ActionBus
from multiprocess_framework.modules.actions_module.schemas import Action


def make_action(
    action_type: str = "SET_VALUE",
    forward_patch: dict | None = None,
    backward_patch: dict | None = None,
    coalesce_key: str | None = None,
    undoable: bool = True,
) -> Action:
    return Action(
        action_type=action_type,
        forward_patch=forward_patch or {"value": 1},
        backward_patch=backward_patch or {"value": 0},
        coalesce_key=coalesce_key,
        undoable=undoable,
    )


def make_rm() -> MagicMock:
    rm = MagicMock()
    rm.set_field_value.return_value = (True, None)
    return rm


def make_handler() -> MagicMock:
    handler = MagicMock()
    handler.apply.return_value = None
    handler.revert.return_value = None
    return handler


@pytest.fixture
def bus():
    rm = make_rm()
    b = ActionBus(rm, max_history=10)
    return b, rm


class TestActionBusExecute:
    def test_execute_calls_handler_apply(self, bus):
        b, rm = bus
        handler = make_handler()
        b.register_handler("SET_VALUE", handler)
        action = make_action("SET_VALUE")
        b.execute(action)
        handler.apply.assert_called_once_with(action, rm)

    def test_execute_no_handler_skips_silently(self, bus):
        b, rm = bus
        action = make_action("UNKNOWN")
        b.execute(action)  # не должно падать
        assert b.can_undo() is False

    def test_execute_adds_to_undo_stack(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        b.execute(make_action("SET_VALUE"))
        assert b.can_undo() is True

    def test_execute_clears_redo_stack(self, bus):
        b, rm = bus
        handler = make_handler()
        b.register_handler("SET_VALUE", handler)
        b.execute(make_action())
        b.undo()
        assert b.can_redo() is True
        b.execute(make_action())
        assert b.can_redo() is False

    def test_execute_command_not_in_undo_stack(self, bus):
        b, rm = bus
        b.register_handler("CMD", make_handler())
        b.execute(make_action("CMD", undoable=False))
        assert b.can_undo() is False
        assert b.last_event is not None
        event_type, _ = b.last_event
        assert event_type == "execute"

    def test_execute_sets_last_event(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        action = make_action()
        b.execute(action)
        event_type, ev_action = b.last_event
        assert event_type == "execute"
        assert ev_action.action_type == "SET_VALUE"

    def test_execute_notifies_callbacks(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        called = []
        b.add_change_callback(lambda: called.append(1))
        b.execute(make_action())
        assert len(called) == 1

    def test_max_history_trimmed(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        for _ in range(15):
            b.execute(make_action())
        assert len(b.history(100)) == 10


class TestActionBusExecuteReturnValue:
    """Тесты на возвращаемое значение execute() -> bool (Phase 2.0 pilot)."""

    def test_execute_returns_true_on_success(self, bus):
        """execute() возвращает True при успешном handler.apply()."""
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        result = b.execute(make_action("SET_VALUE"))
        assert result is True

    def test_execute_returns_false_when_pre_execute_hook_rejects(self, bus):
        """execute() возвращает False если pre_execute_hook вернул False."""
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        b.set_pre_execute_hook(lambda action: False)
        result = b.execute(make_action("SET_VALUE"))
        assert result is False

    def test_execute_returns_false_when_handler_not_found(self, bus):
        """execute() возвращает False если handler не зарегистрирован."""
        b, rm = bus
        result = b.execute(make_action("UNKNOWN_TYPE"))
        assert result is False


class TestActionBusCoalescing:
    def test_coalesce_same_key_merges(self, bus):
        b, rm = bus
        b.register_handler("SLIDE", make_handler())
        a1 = make_action("SLIDE", {"v": 10}, {"v": 0}, coalesce_key="slider:threshold")
        a2 = make_action("SLIDE", {"v": 20}, {"v": 5}, coalesce_key="slider:threshold")
        b.execute(a1)
        b.execute(a2)
        # В стеке должна быть одна запись
        assert len(b.history()) == 1
        merged = b.last_action()
        # forward_patch от a2, backward_patch от a1
        assert merged.forward_patch == {"v": 20}
        assert merged.backward_patch == {"v": 0}

    def test_coalesce_different_keys_not_merged(self, bus):
        b, rm = bus
        b.register_handler("SLIDE", make_handler())
        a1 = make_action("SLIDE", coalesce_key="k1")
        a2 = make_action("SLIDE", coalesce_key="k2")
        b.execute(a1)
        b.execute(a2)
        assert len(b.history()) == 2

    def test_coalesce_none_key_not_merged(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        b.execute(make_action())
        b.execute(make_action())
        assert len(b.history()) == 2


class TestActionBusUndoRedo:
    def test_undo_calls_handler_revert(self, bus):
        b, rm = bus
        handler = make_handler()
        b.register_handler("SET_VALUE", handler)
        action = make_action()
        b.execute(action)
        b.undo()
        handler.revert.assert_called_once()

    def test_undo_removes_from_undo_stack(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        b.execute(make_action())
        assert b.can_undo() is True
        b.undo()
        assert b.can_undo() is False

    def test_undo_adds_to_redo_stack(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        b.execute(make_action())
        b.undo()
        assert b.can_redo() is True

    def test_undo_empty_stack_returns_none(self, bus):
        b, _ = bus
        assert b.undo() is None

    def test_redo_reapplies_action(self, bus):
        b, rm = bus
        handler = make_handler()
        b.register_handler("SET_VALUE", handler)
        b.execute(make_action())
        b.undo()
        b.redo()
        assert handler.apply.call_count == 2

    def test_redo_empty_stack_returns_none(self, bus):
        b, _ = bus
        assert b.redo() is None

    def test_undo_to_specific_action(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        actions = [make_action() for _ in range(5)]
        for a in actions:
            b.execute(a)
        # undo_to(a1) → откатывает a4, a3, a2, a1 → в стеке остаётся [a0]
        target_id = actions[1].action_id
        steps = b.undo_to(target_id)
        assert steps == 4
        assert len(b.history()) == 1

    def test_undo_to_unknown_id_returns_zero(self, bus):
        b, _ = bus
        b.register_handler("SET_VALUE", make_handler())
        b.execute(make_action())
        steps = b.undo_to("nonexistent-id")
        assert steps == 0


class TestActionBusRecord:
    def test_record_adds_to_undo_stack(self, bus):
        b, _ = bus
        action = make_action()
        b.record(action)
        assert b.can_undo() is True

    def test_record_command_not_added(self, bus):
        b, _ = bus
        action = make_action(undoable=False)
        b.record(action)
        assert b.can_undo() is False


class TestActionBusCallbacks:
    def test_add_remove_callback(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        called = []

        def cb():
            called.append(1)

        b.add_change_callback(cb)
        b.execute(make_action())
        assert len(called) == 1
        b.remove_change_callback(cb)
        b.execute(make_action())
        assert len(called) == 1  # не вызван повторно

    def test_remove_nonexistent_callback_no_error(self, bus):
        b, _ = bus
        b.remove_change_callback(lambda: None)  # не падает

    def test_callback_exception_does_not_propagate(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        b.add_change_callback(lambda: (_ for _ in ()).throw(RuntimeError("oops")))
        b.execute(make_action())  # не должно падать


class TestActionBusClear:
    def test_clear_resets_stacks_and_event(self, bus):
        b, rm = bus
        b.register_handler("SET_VALUE", make_handler())
        b.execute(make_action())
        b.undo()
        b.clear()
        assert b.can_undo() is False
        assert b.can_redo() is False
        assert b.last_event is None
