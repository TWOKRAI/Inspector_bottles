"""Тесты NodeMoveHandler и builder-методов V2ActionBuilder (Task 13.1b)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_prototype.frontend.actions.handlers.node_move_handler import NodeMoveHandler
from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
from multiprocess_prototype.frontend.actions.action_types import (
    NODE_MOVE,
    PROCESS_ADD,
    PROCESS_REMOVE,
    WIRE_ADD,
    WIRE_REMOVE,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_move_action(
    node_id: str = "node_1",
    new_x: float = 100.0,
    new_y: float = 200.0,
    old_x: float = 0.0,
    old_y: float = 0.0,
) -> Action:
    """Фабрика Action типа node_move для тестов."""
    return Action(
        action_type=NODE_MOVE,
        forward_patch={"node_id": node_id, "x": new_x, "y": new_y},
        backward_patch={"node_id": node_id, "x": old_x, "y": old_y},
    )


# ---------------------------------------------------------------------------
# Тесты NodeMoveHandler
# ---------------------------------------------------------------------------


class TestNodeMoveHandlerApply:
    def test_apply_calls_callback(self) -> None:
        """apply вызывает on_position_changed с аргументами из forward_patch."""
        callback = MagicMock()
        handler = NodeMoveHandler(on_position_changed=callback)
        action = _make_move_action(node_id="n1", new_x=50.0, new_y=75.0)

        handler.apply(action, rm=None)

        callback.assert_called_once_with("n1", 50.0, 75.0)

    def test_revert_calls_callback(self) -> None:
        """revert вызывает on_position_changed с аргументами из backward_patch."""
        callback = MagicMock()
        handler = NodeMoveHandler(on_position_changed=callback)
        action = _make_move_action(node_id="n2", new_x=50.0, new_y=75.0, old_x=10.0, old_y=20.0)

        handler.revert(action, rm=None)

        callback.assert_called_once_with("n2", 10.0, 20.0)

    def test_no_callback_graceful(self) -> None:
        """Без callback apply и revert не падают."""
        handler = NodeMoveHandler(on_position_changed=None)
        action = _make_move_action()

        # Не должно бросать исключений
        handler.apply(action, rm=None)
        handler.revert(action, rm=None)

    def test_empty_node_id_skipped_apply(self) -> None:
        """apply с пустым node_id не вызывает callback."""
        callback = MagicMock()
        handler = NodeMoveHandler(on_position_changed=callback)
        action = Action(
            action_type=NODE_MOVE,
            forward_patch={"node_id": "", "x": 10.0, "y": 20.0},
            backward_patch={"node_id": "", "x": 0.0, "y": 0.0},
        )

        handler.apply(action, rm=None)

        callback.assert_not_called()

    def test_empty_node_id_skipped_revert(self) -> None:
        """revert с пустым node_id не вызывает callback."""
        callback = MagicMock()
        handler = NodeMoveHandler(on_position_changed=callback)
        action = Action(
            action_type=NODE_MOVE,
            forward_patch={"node_id": "", "x": 10.0, "y": 20.0},
            backward_patch={"node_id": "", "x": 0.0, "y": 0.0},
        )

        handler.revert(action, rm=None)

        callback.assert_not_called()

    def test_missing_node_id_skipped(self) -> None:
        """apply без ключа node_id в патче не вызывает callback."""
        callback = MagicMock()
        handler = NodeMoveHandler(on_position_changed=callback)
        action = Action(
            action_type=NODE_MOVE,
            forward_patch={"x": 10.0, "y": 20.0},
            backward_patch={"x": 0.0, "y": 0.0},
        )

        handler.apply(action, rm=None)

        callback.assert_not_called()


# ---------------------------------------------------------------------------
# Тесты builder-методов V2ActionBuilder
# ---------------------------------------------------------------------------


class TestBuilderNodeMove:
    def test_builder_node_move_action_type(self) -> None:
        """V2ActionBuilder.node_move() создаёт Action с типом NODE_MOVE."""
        action = V2ActionBuilder.node_move("n1", 0.0, 0.0, 100.0, 200.0)

        assert action.action_type == NODE_MOVE

    def test_builder_node_move_patches(self) -> None:
        """V2ActionBuilder.node_move() корректно заполняет forward/backward патчи."""
        action = V2ActionBuilder.node_move("n1", old_x=5.0, old_y=10.0, new_x=50.0, new_y=80.0)

        assert action.forward_patch == {"node_id": "n1", "x": 50.0, "y": 80.0}
        assert action.backward_patch == {"node_id": "n1", "x": 5.0, "y": 10.0}

    def test_builder_node_move_undoable(self) -> None:
        """V2ActionBuilder.node_move() создаёт undoable Action."""
        action = V2ActionBuilder.node_move("n1", 0.0, 0.0, 1.0, 1.0)

        assert action.undoable is True

    def test_builder_node_move_coalesce_key(self) -> None:
        """V2ActionBuilder.node_move() устанавливает coalesce_key."""
        action = V2ActionBuilder.node_move("n1", 0.0, 0.0, 1.0, 1.0)

        assert action.coalesce_key is not None
        assert "move:n1:" in action.coalesce_key

    def test_builder_node_move_description(self) -> None:
        """V2ActionBuilder.node_move() включает node_id в description."""
        action = V2ActionBuilder.node_move("my_node", 0.0, 0.0, 1.0, 1.0)

        assert "my_node" in action.description


class TestBuilderProcessAdd:
    def test_builder_process_add(self) -> None:
        """V2ActionBuilder.process_add() создаёт корректный Action."""
        prev = {"processes": [], "wires": []}
        new = {"processes": [{"id": "p1"}], "wires": []}

        action = V2ActionBuilder.process_add(prev, new, process_name="p1")

        assert action.action_type == PROCESS_ADD
        assert action.forward_patch == {"topology": new}
        assert action.backward_patch == {"topology": prev}
        assert action.undoable is True
        assert "p1" in action.description

    def test_builder_process_remove(self) -> None:
        """V2ActionBuilder.process_remove() создаёт корректный Action."""
        prev = {"processes": [{"id": "p1"}], "wires": []}
        new = {"processes": [], "wires": []}

        action = V2ActionBuilder.process_remove(prev, new, process_name="p1")

        assert action.action_type == PROCESS_REMOVE
        assert action.forward_patch == {"topology": new}
        assert action.backward_patch == {"topology": prev}
        assert action.undoable is True

    def test_builder_wire_add(self) -> None:
        """V2ActionBuilder.wire_add() создаёт корректный Action."""
        prev: dict[str, Any] = {"processes": [], "wires": []}
        new: dict[str, Any] = {"processes": [], "wires": [{"src": "a", "dst": "b"}]}

        action = V2ActionBuilder.wire_add(prev, new, source="a", target="b")

        assert action.action_type == WIRE_ADD
        assert action.forward_patch == {"topology": new}
        assert action.undoable is True
        assert "a" in action.description
        assert "b" in action.description

    def test_builder_wire_remove(self) -> None:
        """V2ActionBuilder.wire_remove() создаёт корректный Action."""
        prev: dict[str, Any] = {"processes": [], "wires": [{"src": "a", "dst": "b"}]}
        new: dict[str, Any] = {"processes": [], "wires": []}

        action = V2ActionBuilder.wire_remove(prev, new, source="a", target="b")

        assert action.action_type == WIRE_REMOVE
        assert action.backward_patch == {"topology": prev}
        assert action.undoable is True
