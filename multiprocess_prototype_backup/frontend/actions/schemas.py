# -*- coding: utf-8 -*-
"""
Domain action types для Inspector Bottles.

Базовый класс Action живёт в фреймворке. Здесь -- доменные типы.
"""
from __future__ import annotations

from enum import Enum

from multiprocess_framework.modules.frontend_module.actions.schemas import Action

# Реэкспорт для обратной совместимости
__all__ = ["Action", "ActionType", "AppActionType"]


class AppActionType(str, Enum):
    """Все доменные типы action для Inspector Bottles."""

    # --- Поля регистров ---
    FIELD_SET = "field_set"

    # --- Регионы (ROI) ---
    REGION_ADD = "region_add"
    REGION_REMOVE = "region_remove"

    # --- Шаги обработки (pipeline steps) ---
    STEP_ADD = "step_add"
    STEP_REMOVE = "step_remove"
    STEP_MODIFY = "step_modify"
    STEP_REORDER = "step_reorder"

    # --- Отображение (display подписки) ---
    DISPLAY_SUBSCRIBE = "display_subscribe"
    DISPLAY_UNSUBSCRIBE = "display_unsubscribe"
    LAYOUT_CHANGE = "layout_change"

    # --- Профили и рецепты ---
    PROFILE_SWITCH = "profile_switch"
    RECIPE_SWITCH = "recipe_switch"

    # --- Side-effect команда без undo ---
    COMMAND = "command"

    # --- Графовый редактор (Phase 8) ---
    GRAPH_CONNECT = "graph_connect"
    GRAPH_DISCONNECT = "graph_disconnect"
    GRAPH_NODE_ADD = "graph_node_add"
    GRAPH_NODE_REMOVE = "graph_node_remove"
    GRAPH_NODE_MOVE = "graph_node_move"
    GRAPH_NODE_MODIFY = "graph_node_modify"

    # --- Редактор топологии (Sources) ---
    TOPOLOGY_CAMERA_ADD = "topology_camera_add"
    TOPOLOGY_CAMERA_REMOVE = "topology_camera_remove"
    TOPOLOGY_REGION_ADD = "topology_region_add"
    TOPOLOGY_REGION_REMOVE = "topology_region_remove"
    TOPOLOGY_MODIFY = "topology_modify"
    TOPOLOGY_REORDER = "topology_reorder"


# Alias для обратной совместимости
ActionType = AppActionType
