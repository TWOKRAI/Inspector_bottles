"""
Unit-тесты ActionBus (Phase 7, Task 7D.4).

Проверяем: execute/undo/redo, coalescing, max_history, callbacks,
can_undo/can_redo, history, undo_to, record, COMMAND type, clear().
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Добавляем корень multiprocess_prototype в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.actions.builder import ActionBuilder
from frontend.actions.bus import ActionBus
from frontend.actions.schemas import ActionType

# ---------------------------------------------------------------------------
# Вспомогательные классы
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager для тестов без Qt и реальной БД."""

    def __init__(self):
        self._data = {}  # {(register_name, field_name): value}

    def set_field_value(self, register_name, field_name, value):
        self._data[(register_name, field_name)] = value
        return (True, None)

    def get_field_value(self, register_name, field_name):
        return self._data.get((register_name, field_name))

    def get_register(self, register_name):
        return None

    def model_dump_all(self):
        result = {}
        for (reg, field), val in self._data.items():
            result.setdefault(reg, {})[field] = val
        return result


class MockHandler:
    """Мок-обработчик, записывающий вызовы apply/revert."""

    def __init__(self):
        self.apply_calls = []
        self.revert_calls = []

    def apply(self, action, rm):
        self.apply_calls.append(action)

    def revert(self, action, rm):
        self.revert_calls.append(action)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture()
def rm():
    return MockRM()


@pytest.fixture()
def handler():
    return MockHandler()


@pytest.fixture()
def bus_with_handler(rm, handler):
    """ActionBus с зарегистрированным MockHandler для FIELD_SET."""
    bus = ActionBus(rm)
    bus.register_handler(ActionType.FIELD_SET, handler)
    return bus, handler


# ---------------------------------------------------------------------------
# Тесты execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_calls_handler_apply(self, bus_with_handler):
        """execute → handler.apply вызван с нужным action."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        assert len(handler.apply_calls) == 1
        assert handler.apply_calls[0].action_id == action.action_id

    def test_execute_adds_action_to_undo_stack(self, bus_with_handler):
        """execute → action добавляется в undo_stack."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        assert bus.can_undo()

    def test_execute_clears_redo_stack(self, rm, handler):
        """execute нового action → redo_stack очищается."""
        bus = ActionBus(rm)
        bus.register_handler(ActionType.FIELD_SET, handler)
        # Добавляем, отменяем, потом выполняем новое
        a1 = ActionBuilder.field_set("reg", "f", 1, 0)
        bus.execute(a1)
        bus.undo()
        assert bus.can_redo()
        # Новое действие должно очистить redo
        a2 = ActionBuilder.field_set("reg", "f", 2, 0)
        bus.execute(a2)
        assert not bus.can_redo()

    def test_execute_no_handler_registered_does_nothing(self, rm):
        """execute без зарегистрированного handler → action пропускается, нет исключения."""
        bus = ActionBus(rm)
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)  # не должно бросить исключение
        assert not bus.can_undo()


# ---------------------------------------------------------------------------
# Тесты undo
# ---------------------------------------------------------------------------


class TestUndo:
    def test_undo_calls_handler_revert(self, bus_with_handler):
        """undo → handler.revert вызван."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        bus.undo()
        assert len(handler.revert_calls) == 1

    def test_undo_moves_action_to_redo_stack(self, bus_with_handler):
        """undo → action перемещается в redo_stack."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        bus.undo()
        assert not bus.can_undo()
        assert bus.can_redo()

    def test_undo_returns_action(self, bus_with_handler):
        """undo → возвращает отменённый Action."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        result = bus.undo()
        assert result is not None
        assert result.action_type == ActionType.FIELD_SET

    def test_undo_on_empty_stack_returns_none(self, rm):
        """undo на пустом стеке → возвращает None, без исключений."""
        bus = ActionBus(rm)
        result = bus.undo()
        assert result is None


# ---------------------------------------------------------------------------
# Тесты redo
# ---------------------------------------------------------------------------


class TestRedo:
    def test_redo_calls_handler_apply_again(self, bus_with_handler):
        """redo → handler.apply вызван повторно."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        bus.undo()
        bus.redo()
        assert len(handler.apply_calls) == 2  # execute + redo

    def test_redo_moves_action_back_to_undo_stack(self, bus_with_handler):
        """redo → action возвращается в undo_stack."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        bus.undo()
        bus.redo()
        assert bus.can_undo()
        assert not bus.can_redo()

    def test_redo_returns_action(self, bus_with_handler):
        """redo → возвращает повторённый Action."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "field", 1, 0)
        bus.execute(action)
        bus.undo()
        result = bus.redo()
        assert result is not None

    def test_redo_on_empty_stack_returns_none(self, rm):
        """redo на пустом redo-стеке → возвращает None."""
        bus = ActionBus(rm)
        result = bus.redo()
        assert result is None


# ---------------------------------------------------------------------------
# Тесты coalescing
# ---------------------------------------------------------------------------


class TestCoalescing:
    def test_coalescing_three_same_field_gives_one_stack_entry(self, rm, handler):
        """3 field_set для одного поля → 1 запись в undo_stack (coalescing)."""
        bus = ActionBus(rm)
        bus.register_handler(ActionType.FIELD_SET, handler)
        for v in [10, 20, 30]:
            bus.execute(ActionBuilder.field_set("reg", "threshold", v, v - 10))
        assert len(bus.history()) == 1

    def test_coalescing_backward_patch_from_first_action(self, rm, handler):
        """После coalescing backward_patch берётся от первого action."""
        bus = ActionBus(rm)
        bus.register_handler(ActionType.FIELD_SET, handler)
        a1 = ActionBuilder.field_set("reg", "f", 10, 0)
        a2 = ActionBuilder.field_set("reg", "f", 20, 10)
        a3 = ActionBuilder.field_set("reg", "f", 30, 20)
        bus.execute(a1)
        bus.execute(a2)
        bus.execute(a3)
        merged = bus.history()[-1]
        # backward_patch должен быть от первого (old_value=0)
        assert merged.backward_patch["value"] == 0

    def test_coalescing_different_fields_no_merge(self, rm, handler):
        """field_set для разных полей → 2 записи в стеке (нет coalescing)."""
        bus = ActionBus(rm)
        bus.register_handler(ActionType.FIELD_SET, handler)
        bus.execute(ActionBuilder.field_set("reg", "field_a", 1, 0))
        bus.execute(ActionBuilder.field_set("reg", "field_b", 2, 0))
        assert len(bus.history()) == 2


# ---------------------------------------------------------------------------
# Тесты max_history
# ---------------------------------------------------------------------------


class TestMaxHistory:
    def test_max_history_limits_stack_size(self, rm, handler):
        """max_history=5, 7 actions → стек содержит 5 записей."""
        bus = ActionBus(rm, max_history=5)
        bus.register_handler(ActionType.FIELD_SET, handler)
        # Разные поля — нет coalescing
        for i in range(7):
            bus.execute(ActionBuilder.field_set("reg", f"field_{i}", i + 1, i))
        assert len(bus.history()) == 5

    def test_max_history_keeps_newest_actions(self, rm, handler):
        """При переполнении max_history — сохраняются новейшие actions."""
        bus = ActionBus(rm, max_history=3)
        bus.register_handler(ActionType.FIELD_SET, handler)
        for i in range(5):
            bus.execute(ActionBuilder.field_set("reg", f"f{i}", i + 1, i))
        history = bus.history()
        # Последнее в стеке — самое новое (field_4)
        assert history[-1].field_name == "f4"


# ---------------------------------------------------------------------------
# Тесты COMMAND type
# ---------------------------------------------------------------------------


class TestCommandType:
    def test_command_not_added_to_undo_stack(self, rm):
        """COMMAND action → НЕ добавляется в undo_stack."""
        bus = ActionBus(rm)
        cmd_handler = MockHandler()
        bus.register_handler(ActionType.COMMAND, cmd_handler)
        action = ActionBuilder.command("Тест")
        bus.execute(action)
        assert not bus.can_undo()

    def test_command_handler_apply_is_called(self, rm):
        """COMMAND action → handler.apply вызывается."""
        bus = ActionBus(rm)
        cmd_handler = MockHandler()
        bus.register_handler(ActionType.COMMAND, cmd_handler)
        action = ActionBuilder.command("Тест")
        bus.execute(action)
        assert len(cmd_handler.apply_calls) == 1


# ---------------------------------------------------------------------------
# Тесты can_undo / can_redo
# ---------------------------------------------------------------------------


class TestCanUndoRedo:
    def test_can_undo_false_at_start(self, rm):
        """can_undo=False при пустом стеке."""
        bus = ActionBus(rm)
        assert not bus.can_undo()

    def test_can_undo_true_after_execute(self, bus_with_handler):
        """can_undo=True после execute."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        assert bus.can_undo()

    def test_can_redo_false_at_start(self, rm):
        """can_redo=False при пустом redo-стеке."""
        bus = ActionBus(rm)
        assert not bus.can_redo()

    def test_can_redo_true_after_undo(self, bus_with_handler):
        """can_redo=True после undo."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        bus.undo()
        assert bus.can_redo()


# ---------------------------------------------------------------------------
# Тесты undo_to
# ---------------------------------------------------------------------------


class TestUndoTo:
    def test_undo_to_performs_n_undo_steps(self, rm, handler):
        """undo_to(action_id) → выполняет N шагов undo до target включительно."""
        bus = ActionBus(rm, max_history=10)
        bus.register_handler(ActionType.FIELD_SET, handler)
        actions = []
        for i in range(4):
            a = ActionBuilder.field_set("reg", f"f{i}", i + 1, i)
            bus.execute(a)
            actions.append(a)
        # Откатываем до второго action (индекс 1) — должно быть 3 шага
        steps = bus.undo_to(actions[1].action_id)
        assert steps == 3

    def test_undo_to_unknown_id_returns_zero(self, bus_with_handler):
        """undo_to с несуществующим action_id → возвращает 0, стек не меняется."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        steps = bus.undo_to("non-existent-id")
        assert steps == 0
        assert bus.can_undo()  # стек не изменился


# ---------------------------------------------------------------------------
# Тесты callbacks
# ---------------------------------------------------------------------------


class TestCallbacks:
    def test_callback_called_after_execute(self, bus_with_handler):
        """Callback вызывается после execute."""
        bus, handler = bus_with_handler
        calls = []
        bus.add_change_callback(lambda: calls.append("cb"))
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        assert len(calls) == 1

    def test_callback_called_after_undo(self, bus_with_handler):
        """Callback вызывается после undo."""
        bus, handler = bus_with_handler
        calls = []
        bus.add_change_callback(lambda: calls.append("cb"))
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        calls.clear()
        bus.undo()
        assert len(calls) == 1

    def test_callback_called_after_redo(self, bus_with_handler):
        """Callback вызывается после redo."""
        bus, handler = bus_with_handler
        calls = []
        bus.add_change_callback(lambda: calls.append("cb"))
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        bus.undo()
        calls.clear()
        bus.redo()
        assert len(calls) == 1

    def test_remove_callback(self, bus_with_handler):
        """remove_change_callback → callback больше не вызывается."""
        bus, handler = bus_with_handler
        calls = []
        cb = lambda: calls.append("cb")
        bus.add_change_callback(cb)
        bus.remove_change_callback(cb)
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# Тесты last_event
# ---------------------------------------------------------------------------


class TestLastEvent:
    def test_last_event_after_execute(self, bus_with_handler):
        """last_event после execute → ("execute", action)."""
        bus, handler = bus_with_handler
        action = ActionBuilder.field_set("reg", "f", 1, 0)
        bus.execute(action)
        event_type, event_action = bus.last_event
        assert event_type == "execute"

    def test_last_event_after_undo(self, bus_with_handler):
        """last_event после undo → ("undo", action)."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        bus.undo()
        event_type, _ = bus.last_event
        assert event_type == "undo"

    def test_last_event_after_redo(self, bus_with_handler):
        """last_event после redo → ("redo", action)."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        bus.undo()
        bus.redo()
        event_type, _ = bus.last_event
        assert event_type == "redo"

    def test_last_event_none_at_start(self, rm):
        """last_event=None при старте (стек пустой)."""
        bus = ActionBus(rm)
        assert bus.last_event is None


# ---------------------------------------------------------------------------
# Тесты record()
# ---------------------------------------------------------------------------


class TestRecord:
    def test_record_adds_to_stack_without_apply(self, rm, handler):
        """record() добавляет action в стек без вызова handler.apply."""
        bus = ActionBus(rm)
        bus.register_handler(ActionType.FIELD_SET, handler)
        action = ActionBuilder.field_set("reg", "f", 1, 0)
        bus.record(action)
        assert bus.can_undo()
        assert len(handler.apply_calls) == 0  # apply не вызывался

    def test_record_command_not_in_stack(self, rm):
        """record() с undoable=False → action не попадает в стек."""
        bus = ActionBus(rm)
        cmd_handler = MockHandler()
        bus.register_handler(ActionType.COMMAND, cmd_handler)
        action = ActionBuilder.command("cmd")
        bus.record(action)
        assert not bus.can_undo()


# ---------------------------------------------------------------------------
# Тесты clear()
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_empties_undo_stack(self, bus_with_handler):
        """clear() очищает undo_stack."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        bus.clear()
        assert not bus.can_undo()

    def test_clear_empties_redo_stack(self, bus_with_handler):
        """clear() очищает redo_stack."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        bus.undo()
        bus.clear()
        assert not bus.can_redo()

    def test_clear_resets_last_event(self, bus_with_handler):
        """clear() сбрасывает last_event в None."""
        bus, handler = bus_with_handler
        bus.execute(ActionBuilder.field_set("reg", "f", 1, 0))
        bus.clear()
        assert bus.last_event is None
