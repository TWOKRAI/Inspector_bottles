"""
Unit-тесты для GRAPH_* действий (Task 8.8).

Покрывает:
  - ActionBuilder методы graph_connect/disconnect/node_add/node_remove/node_move
  - GraphActionHandler: apply/revert для каждого типа
  - ActionBus: execute → undo → redo для графовых операций
  - Coalescing GRAPH_NODE_MOVE: серия перемещений = 1 Action в стеке
  - graph_node_remove → undo → узлы восстановлены

Без Qt, без реальной БД — только мок-зависимости.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень multiprocess_prototype в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.actions.builder import ActionBuilder  # noqa: E402
from frontend.actions.default_bus_factory import create_default_action_bus  # noqa: E402
from frontend.actions.handlers.graph_handler import GraphActionHandler  # noqa: E402
from frontend.actions.schemas import Action, ActionType  # noqa: E402

# ---------------------------------------------------------------------------
# Мок RegistersManager
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager без Qt и реальной БД."""

    def __init__(self):
        self._data: dict = {}  # {(register_name, field_name): value}
        self.calls: list = []  # история вызовов set_field_value

    def set_field_value(self, register_name, field_name, value):
        self._data[(register_name, field_name)] = value
        self.calls.append((register_name, field_name, value))
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


# ---------------------------------------------------------------------------
# Тесты ActionBuilder.graph_* методов
# ---------------------------------------------------------------------------


class TestGraphActionBuilder:
    """Тесты фабричных методов ActionBuilder для GRAPH_* операций."""

    def test_graph_connect_creates_correct_action_type(self):
        """graph_connect → ActionType.GRAPH_CONNECT."""
        action = ActionBuilder.graph_connect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before={"a": 1},
            nodes_after={"a": 2},
        )
        assert action.action_type == ActionType.GRAPH_CONNECT

    def test_graph_connect_forward_patch_contains_nodes_after(self):
        """graph_connect → forward_patch['nodes_after'] соответствует переданному значению."""
        nodes_after = {"node_a": {"connections": ["node_b"]}}
        action = ActionBuilder.graph_connect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before={},
            nodes_after=nodes_after,
        )
        assert action.forward_patch["nodes_after"] == nodes_after

    def test_graph_connect_backward_patch_contains_nodes_before(self):
        """graph_connect → backward_patch['nodes_before'] соответствует переданному значению."""
        nodes_before = {"node_a": {"connections": []}}
        action = ActionBuilder.graph_connect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before=nodes_before,
            nodes_after={},
        )
        assert action.backward_patch["nodes_before"] == nodes_before

    def test_graph_connect_is_undoable(self):
        """graph_connect → undoable=True."""
        action = ActionBuilder.graph_connect(
            "r",
            "a",
            "o",
            "b",
            "i",
            {},
            {},
        )
        assert action.undoable is True

    def test_graph_disconnect_creates_correct_action_type(self):
        """graph_disconnect → ActionType.GRAPH_DISCONNECT."""
        action = ActionBuilder.graph_disconnect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before={},
            nodes_after={},
        )
        assert action.action_type == ActionType.GRAPH_DISCONNECT

    def test_graph_node_add_creates_correct_action_type(self):
        """graph_node_add → ActionType.GRAPH_NODE_ADD."""
        action = ActionBuilder.graph_node_add(
            "region_1",
            {"id": "n1"},
            {},
            {"n1": {}},
        )
        assert action.action_type == ActionType.GRAPH_NODE_ADD

    def test_graph_node_add_forward_patch_contains_node_data(self):
        """graph_node_add → forward_patch['node_data'] соответствует переданному значению."""
        node_data = {"id": "n1", "type": "blur"}
        action = ActionBuilder.graph_node_add("r", node_data, {}, {"n1": node_data})
        assert action.forward_patch["node_data"] == node_data

    def test_graph_node_remove_creates_correct_action_type(self):
        """graph_node_remove → ActionType.GRAPH_NODE_REMOVE."""
        action = ActionBuilder.graph_node_remove(
            "region_1",
            "node_x",
            {"node_x": {}},
            {},
        )
        assert action.action_type == ActionType.GRAPH_NODE_REMOVE

    def test_graph_node_move_creates_correct_action_type(self):
        """graph_node_move → ActionType.GRAPH_NODE_MOVE."""
        action = ActionBuilder.graph_node_move("region_1", "node_a", (0.0, 0.0), (10.0, 20.0))
        assert action.action_type == ActionType.GRAPH_NODE_MOVE

    def test_graph_node_move_has_coalesce_key(self):
        """graph_node_move → coalesce_key установлен для группировки перемещений."""
        action = ActionBuilder.graph_node_move("region_1", "node_a", (0.0, 0.0), (10.0, 20.0))
        assert action.coalesce_key == "graph_move:region_1:node_a"

    def test_graph_node_move_forward_patch(self):
        """graph_node_move → forward_patch содержит node_id и new_pos."""
        action = ActionBuilder.graph_node_move("r", "n1", (1.0, 2.0), (5.0, 6.0))
        assert action.forward_patch["node_id"] == "n1"
        assert action.forward_patch["new_pos"] == (5.0, 6.0)

    def test_graph_node_move_backward_patch(self):
        """graph_node_move → backward_patch содержит node_id и old_pos."""
        action = ActionBuilder.graph_node_move("r", "n1", (1.0, 2.0), (5.0, 6.0))
        assert action.backward_patch["node_id"] == "n1"
        assert action.backward_patch["old_pos"] == (1.0, 2.0)

    def test_graph_node_move_register_name(self):
        """graph_node_move → register_name = region_id."""
        action = ActionBuilder.graph_node_move("my_region", "n1", None, (0.0, 0.0))
        assert action.register_name == "my_region"


# ---------------------------------------------------------------------------
# Тесты GraphActionHandler
# ---------------------------------------------------------------------------


class TestGraphActionHandler:
    """Тесты обработчика GRAPH_* действий."""

    def test_apply_graph_connect_writes_nodes_after(self):
        """apply для GRAPH_CONNECT → rm.set_field_value вызван с nodes_after."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_after = {"node_a": {"connected_to": "node_b"}}
        action = ActionBuilder.graph_connect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before={},
            nodes_after=nodes_after,
        )
        handler.apply(action, rm)
        assert ("region_1", "vision_pipeline", nodes_after) in rm.calls

    def test_revert_graph_connect_writes_nodes_before(self):
        """revert для GRAPH_CONNECT → rm.set_field_value вызван с nodes_before."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_before = {"node_a": {"connected_to": None}}
        action = ActionBuilder.graph_connect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before=nodes_before,
            nodes_after={},
        )
        handler.revert(action, rm)
        assert ("region_1", "vision_pipeline", nodes_before) in rm.calls

    def test_apply_graph_disconnect_writes_nodes_after(self):
        """apply для GRAPH_DISCONNECT → rm.set_field_value вызван с nodes_after."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_after = {"node_a": {"connected_to": None}}
        action = ActionBuilder.graph_disconnect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before={},
            nodes_after=nodes_after,
        )
        handler.apply(action, rm)
        assert ("region_1", "vision_pipeline", nodes_after) in rm.calls

    def test_revert_graph_disconnect_writes_nodes_before(self):
        """revert для GRAPH_DISCONNECT → rm.set_field_value вызван с nodes_before."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_before = {"node_a": {"connected_to": "node_b"}}
        action = ActionBuilder.graph_disconnect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before=nodes_before,
            nodes_after={},
        )
        handler.revert(action, rm)
        assert ("region_1", "vision_pipeline", nodes_before) in rm.calls

    def test_apply_graph_node_add_writes_nodes_after(self):
        """apply для GRAPH_NODE_ADD → rm.set_field_value вызван с nodes_after."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_after = {"n1": {"type": "blur"}}
        action = ActionBuilder.graph_node_add("region_1", {"id": "n1"}, {}, nodes_after)
        handler.apply(action, rm)
        assert ("region_1", "vision_pipeline", nodes_after) in rm.calls

    def test_revert_graph_node_add_writes_nodes_before(self):
        """revert для GRAPH_NODE_ADD → rm.set_field_value вызван с nodes_before (пустое)."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_before: dict = {}
        action = ActionBuilder.graph_node_add("region_1", {"id": "n1"}, nodes_before, {"n1": {}})
        handler.revert(action, rm)
        assert ("region_1", "vision_pipeline", nodes_before) in rm.calls

    def test_apply_graph_node_remove_writes_nodes_after(self):
        """apply для GRAPH_NODE_REMOVE → rm.set_field_value вызван с nodes_after."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_after: dict = {}
        action = ActionBuilder.graph_node_remove("region_1", "n1", {"n1": {}}, nodes_after)
        handler.apply(action, rm)
        assert ("region_1", "vision_pipeline", nodes_after) in rm.calls

    def test_revert_graph_node_remove_writes_nodes_before(self):
        """revert для GRAPH_NODE_REMOVE → rm.set_field_value вызван с nodes_before."""
        rm = MockRM()
        handler = GraphActionHandler()
        nodes_before = {"n1": {"type": "edge_detect"}}
        action = ActionBuilder.graph_node_remove("region_1", "n1", nodes_before, {})
        handler.revert(action, rm)
        assert ("region_1", "vision_pipeline", nodes_before) in rm.calls

    def test_apply_graph_node_move_no_rm_call(self):
        """apply для GRAPH_NODE_MOVE → rm.set_field_value НЕ вызывается (только лог)."""
        rm = MockRM()
        handler = GraphActionHandler()
        action = ActionBuilder.graph_node_move("region_1", "n1", (0.0, 0.0), (10.0, 20.0))
        handler.apply(action, rm)
        assert len(rm.calls) == 0

    def test_revert_graph_node_move_no_rm_call(self):
        """revert для GRAPH_NODE_MOVE → rm.set_field_value НЕ вызывается (только лог)."""
        rm = MockRM()
        handler = GraphActionHandler()
        action = ActionBuilder.graph_node_move("region_1", "n1", (5.0, 5.0), (10.0, 20.0))
        handler.revert(action, rm)
        assert len(rm.calls) == 0

    def test_apply_missing_nodes_after_no_exception(self):
        """apply без nodes_after → warning, нет исключения, rm не вызывается."""
        rm = MockRM()
        handler = GraphActionHandler()
        action = Action(
            action_type=ActionType.GRAPH_CONNECT,
            register_name="region_1",
            forward_patch={},  # нет nodes_after
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0

    def test_revert_missing_nodes_before_no_exception(self):
        """revert без nodes_before → warning, нет исключения, rm не вызывается."""
        rm = MockRM()
        handler = GraphActionHandler()
        action = Action(
            action_type=ActionType.GRAPH_DISCONNECT,
            register_name="region_1",
            backward_patch={},  # нет nodes_before
        )
        handler.revert(action, rm)
        assert len(rm.calls) == 0

    def test_apply_missing_register_name_no_exception(self):
        """apply без register_name → warning, нет исключения, rm не вызывается."""
        rm = MockRM()
        handler = GraphActionHandler()
        action = Action(
            action_type=ActionType.GRAPH_NODE_ADD,
            register_name=None,
            forward_patch={"nodes_after": {"n1": {}}},
        )
        handler.apply(action, rm)
        assert len(rm.calls) == 0


# ---------------------------------------------------------------------------
# Тесты ActionBus с GRAPH_* через create_default_action_bus
# ---------------------------------------------------------------------------


class TestGraphActionBus:
    """Интеграционные тесты ActionBus с графовыми операциями."""

    # --- graph_connect: execute → undo → redo ---

    def test_graph_connect_execute_undo_redo(self):
        """graph_connect: execute → undo → связь удалена → redo → восстановлена."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        nodes_before = {"node_a": {"outputs": []}, "node_b": {"inputs": []}}
        nodes_after = {"node_a": {"outputs": ["node_b"]}, "node_b": {"inputs": ["node_a"]}}

        action = ActionBuilder.graph_connect(
            "region_1",
            "node_a",
            "out",
            "node_b",
            "in",
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        # execute → apply: записаны nodes_after
        bus.execute(action)
        assert ("region_1", "vision_pipeline", nodes_after) in rm.calls

        calls_after_execute = len(rm.calls)

        # undo → revert: записаны nodes_before (связь разорвана)
        bus.undo()
        assert len(rm.calls) == calls_after_execute + 1
        assert rm.calls[-1] == ("region_1", "vision_pipeline", nodes_before)

        # redo → apply: снова nodes_after (связь восстановлена)
        bus.redo()
        assert len(rm.calls) == calls_after_execute + 2
        assert rm.calls[-1] == ("region_1", "vision_pipeline", nodes_after)

    def test_graph_connect_execute_pushes_to_undo_stack(self):
        """execute graph_connect → action попадает в undo-стек."""
        rm = MockRM()
        bus = create_default_action_bus(rm)
        action = ActionBuilder.graph_connect("r", "a", "o", "b", "i", {}, {})
        bus.execute(action)
        assert bus.can_undo()

    def test_graph_connect_undo_pushes_to_redo_stack(self):
        """undo после graph_connect → action попадает в redo-стек."""
        rm = MockRM()
        bus = create_default_action_bus(rm)
        action = ActionBuilder.graph_connect("r", "a", "o", "b", "i", {}, {})
        bus.execute(action)
        bus.undo()
        assert bus.can_redo()

    # --- graph_node_add: execute → undo ---

    def test_graph_node_add_execute_undo(self):
        """graph_node_add: execute → undo → узел удалён (nodes_before восстановлен)."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        node_data = {"id": "n1", "type": "threshold"}
        nodes_before: dict = {}
        nodes_after = {"n1": node_data}

        action = ActionBuilder.graph_node_add("region_1", node_data, nodes_before, nodes_after)

        # execute → nodes_after записан
        bus.execute(action)
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_after

        # undo → nodes_before восстановлен
        bus.undo()
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_before

    def test_graph_node_add_undo_clears_redo_on_new_execute(self):
        """После undo → новый execute → redo-стек очищен."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        a1 = ActionBuilder.graph_node_add("r", {"id": "n1"}, {}, {"n1": {}})
        a2 = ActionBuilder.graph_node_add("r", {"id": "n2"}, {"n1": {}}, {"n1": {}, "n2": {}})

        bus.execute(a1)
        bus.undo()
        # redo доступен
        assert bus.can_redo()

        # Новый execute → redo сбрасывается
        bus.execute(a2)
        assert not bus.can_redo()

    # --- graph_node_remove: execute → undo → узлы восстановлены ---

    def test_graph_node_remove_execute_undo(self):
        """graph_node_remove: execute → undo → узел восстановлен."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        nodes_before = {"n1": {"type": "blur"}, "n2": {"type": "edge"}}
        nodes_after = {"n2": {"type": "edge"}}  # n1 удалён

        action = ActionBuilder.graph_node_remove("region_1", "n1", nodes_before, nodes_after)

        # execute → nodes_after (без n1)
        bus.execute(action)
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_after

        # undo → nodes_before (n1 восстановлен)
        bus.undo()
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_before

    def test_graph_node_remove_undo_redo_cycle(self):
        """graph_node_remove: execute → undo → redo → финальное состояние = nodes_after."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        nodes_before = {"n1": {}, "n2": {}}
        nodes_after = {"n2": {}}

        action = ActionBuilder.graph_node_remove("region_1", "n1", nodes_before, nodes_after)

        bus.execute(action)
        bus.undo()
        bus.redo()

        # После redo → состояние как после execute
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_after

    # --- graph_node_move coalescing ---

    def test_graph_node_move_coalescing_ten_moves_one_action(self):
        """graph_node_move: 10 перемещений с одинаковым coalesce_key → 1 Action в стеке."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        # 10 перемещений одного узла
        for i in range(10):
            action = ActionBuilder.graph_node_move(
                "region_1",
                "node_a",
                old_pos=(float(i), float(i)),
                new_pos=(float(i + 1), float(i + 1)),
            )
            bus.execute(action)

        # В undo-стеке должен быть ровно 1 Action
        assert len(bus.history()) == 1

    def test_graph_node_move_coalescing_preserves_first_backward_patch(self):
        """graph_node_move coalescing: backward_patch = от первого перемещения (начальная позиция)."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        start_pos = (0.0, 0.0)

        # Первое перемещение: (0, 0) → (5, 5)
        a1 = ActionBuilder.graph_node_move("region_1", "node_a", start_pos, (5.0, 5.0))
        bus.execute(a1)

        # Последующие перемещения
        for i in range(5, 10):
            action = ActionBuilder.graph_node_move(
                "region_1",
                "node_a",
                old_pos=(float(i), float(i)),
                new_pos=(float(i + 1), float(i + 1)),
            )
            bus.execute(action)

        # В стеке 1 Action; backward_patch.old_pos = начальная позиция
        merged = bus.last_action()
        assert merged is not None
        assert merged.backward_patch["old_pos"] == start_pos

    def test_graph_node_move_coalescing_preserves_last_forward_patch(self):
        """graph_node_move coalescing: forward_patch = от последнего перемещения (финальная позиция)."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        final_pos = (10.0, 10.0)

        for i in range(9):
            action = ActionBuilder.graph_node_move(
                "region_1",
                "node_a",
                old_pos=(float(i), float(i)),
                new_pos=(float(i + 1), float(i + 1)),
            )
            bus.execute(action)

        last_action = ActionBuilder.graph_node_move(
            "region_1",
            "node_a",
            old_pos=(9.0, 9.0),
            new_pos=final_pos,
        )
        bus.execute(last_action)

        merged = bus.last_action()
        assert merged is not None
        assert merged.forward_patch["new_pos"] == final_pos

    def test_graph_node_move_different_nodes_no_coalescing(self):
        """graph_node_move разных узлов → 2 отдельных Action в стеке."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        a1 = ActionBuilder.graph_node_move("region_1", "node_a", (0.0, 0.0), (5.0, 5.0))
        a2 = ActionBuilder.graph_node_move("region_1", "node_b", (0.0, 0.0), (5.0, 5.0))

        bus.execute(a1)
        bus.execute(a2)

        # 2 разных узла → 2 Action в стеке
        assert len(bus.history()) == 2

    # --- graph_disconnect: execute → undo → redo ---

    def test_graph_disconnect_execute_undo_redo(self):
        """graph_disconnect: execute → undo → связь восстановлена → redo → удалена."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        nodes_before = {"a": {"outputs": ["b"]}, "b": {"inputs": ["a"]}}
        nodes_after = {"a": {"outputs": []}, "b": {"inputs": []}}

        action = ActionBuilder.graph_disconnect(
            "region_1",
            "a",
            "out",
            "b",
            "in",
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        bus.execute(action)
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_after

        # undo → восстановлена связь
        bus.undo()
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_before

        # redo → снова разрыв
        bus.redo()
        assert rm.get_field_value("region_1", "vision_pipeline") == nodes_after

    # --- Проверка регистрации в factory ---

    def test_all_graph_handlers_registered(self):
        """create_default_action_bus регистрирует handler для всех 5 GRAPH_* типов."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        graph_types = [
            ActionType.GRAPH_CONNECT,
            ActionType.GRAPH_DISCONNECT,
            ActionType.GRAPH_NODE_ADD,
            ActionType.GRAPH_NODE_REMOVE,
            ActionType.GRAPH_NODE_MOVE,
        ]
        for action_type in graph_types:
            assert action_type in bus._handlers, f"Handler не зарегистрирован для {action_type}"

    def test_all_graph_handlers_are_graph_action_handler(self):
        """Все GRAPH_* типы обрабатываются GraphActionHandler (один экземпляр)."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        graph_types = [
            ActionType.GRAPH_CONNECT,
            ActionType.GRAPH_DISCONNECT,
            ActionType.GRAPH_NODE_ADD,
            ActionType.GRAPH_NODE_REMOVE,
            ActionType.GRAPH_NODE_MOVE,
        ]
        handlers = [bus._handlers[t] for t in graph_types]

        # Все handlers — GraphActionHandler
        for h in handlers:
            assert isinstance(h, GraphActionHandler)

        # Один экземпляр для всех (из factory)
        assert all(h is handlers[0] for h in handlers)
