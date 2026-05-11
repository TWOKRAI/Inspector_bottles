# -*- coding: utf-8 -*-
"""Тесты для NodeMoveHandler (FW)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.actions_module.handlers.move_handler import (
    NodeMoveHandler,
)
from multiprocess_framework.modules.actions_module.schemas import Action


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_move_action(
    forward_node_id: str,
    forward_x: float,
    forward_y: float,
    backward_node_id: str = "n1",
    backward_x: float = 0.0,
    backward_y: float = 0.0,
) -> Action:
    """Создать Action типа NODE_MOVE с координатами."""
    return Action(
        action_type="NODE_MOVE",
        forward_patch={"node_id": forward_node_id, "x": forward_x, "y": forward_y},
        backward_patch={"node_id": backward_node_id, "x": backward_x, "y": backward_y},
    )


# ---------------------------------------------------------------------------
# Тест 1: apply вызывает callback с координатами из forward_patch
# ---------------------------------------------------------------------------

def test_apply_calls_callback_with_forward_coords():
    """apply() передаёт node_id, x, y из forward_patch в callback."""
    callback = MagicMock()
    handler = NodeMoveHandler(on_position_changed=callback)
    action = _make_move_action("node-1", 100.0, 200.0)

    handler.apply(action, rm=None)

    callback.assert_called_once_with("node-1", 100.0, 200.0)


# ---------------------------------------------------------------------------
# Тест 2: revert вызывает callback с координатами из backward_patch
# ---------------------------------------------------------------------------

def test_revert_calls_callback_with_backward_coords():
    """revert() передаёт node_id, x, y из backward_patch в callback."""
    callback = MagicMock()
    handler = NodeMoveHandler(on_position_changed=callback)
    action = _make_move_action(
        forward_node_id="node-1",
        forward_x=100.0,
        forward_y=200.0,
        backward_node_id="node-1",
        backward_x=10.0,
        backward_y=20.0,
    )

    handler.revert(action, rm=None)

    callback.assert_called_once_with("node-1", 10.0, 20.0)


# ---------------------------------------------------------------------------
# Тест 3: apply без callback — не падает
# ---------------------------------------------------------------------------

def test_apply_without_callback_no_crash():
    """apply() без callback выполняется без исключений."""
    handler = NodeMoveHandler()
    action = _make_move_action("node-1", 50.0, 75.0)

    handler.apply(action, rm=None)  # не должно выбросить


# ---------------------------------------------------------------------------
# Тест 4: revert без callback — не падает
# ---------------------------------------------------------------------------

def test_revert_without_callback_no_crash():
    """revert() без callback выполняется без исключений."""
    handler = NodeMoveHandler()
    action = _make_move_action("node-1", 50.0, 75.0, "node-1", 0.0, 0.0)

    handler.revert(action, rm=None)  # не должно выбросить


# ---------------------------------------------------------------------------
# Тест 5: set_callback устанавливает callback post-init
# ---------------------------------------------------------------------------

def test_set_callback_post_init():
    """set_callback() позволяет привязать callback после создания объекта."""
    handler = NodeMoveHandler()
    callback = MagicMock()
    handler.set_callback(callback)
    action = _make_move_action("node-2", 30.0, 40.0)

    handler.apply(action, rm=None)

    callback.assert_called_once_with("node-2", 30.0, 40.0)


# ---------------------------------------------------------------------------
# Тест 6: apply с пустым node_id — ранний выход, callback не вызывается
# ---------------------------------------------------------------------------

def test_apply_empty_node_id_skips_callback(caplog):
    """apply() с пустым node_id логирует warning и не вызывает callback."""
    callback = MagicMock()
    handler = NodeMoveHandler(on_position_changed=callback)
    action = Action(
        action_type="NODE_MOVE",
        forward_patch={"node_id": "", "x": 10.0, "y": 20.0},
        backward_patch={"node_id": "n1", "x": 0.0, "y": 0.0},
    )

    with caplog.at_level(logging.WARNING):
        handler.apply(action, rm=None)

    callback.assert_not_called()
    assert "node_id пуст" in caplog.text
