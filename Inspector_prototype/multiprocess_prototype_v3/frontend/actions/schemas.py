# -*- coding: utf-8 -*-
"""
Action schema — неизменяемая единица изменения состояния.

Action содержит forward_patch (apply) и backward_patch (revert),
что позволяет реализовать полноценный undo/redo.

coalesce_key — ключ группировки: несколько Action с одинаковым ключом
(например, тики слайдера) объединяются в один при coalescing.

Наследуется от SchemaBase для автоматического маппинга полей
и совместимости с data_schema_module.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from data_schema_module import SchemaBase
from pydantic import ConfigDict, Field


class ActionType(str, Enum):
    """Типы действий в системе."""

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


class Action(SchemaBase):
    """
    Неизменяемая единица изменения состояния.

    Содержит достаточно данных для apply() (forward_patch)
    и revert() (backward_patch).

    SQLMeta определяет таблицу для персистентного логирования действий.
    """

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=False,
        populate_by_name=True,
    )

    class SQLMeta:
        """Метаданные для SQL-маппинга."""

        table_name = "action_log"

    # --- Идентификация ---
    action_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Уникальный идентификатор действия (UUID4)",
    )
    action_type: ActionType = Field(
        description="Тип действия",
    )

    # --- Контекст: какой регистр и поле затронуты ---
    register_name: Optional[str] = Field(
        default=None,
        description="Имя регистра (например, 'processing')",
    )
    field_name: Optional[str] = Field(
        default=None,
        description="Имя поля в регистре (например, 'threshold')",
    )

    # --- Патчи для apply/revert ---
    forward_patch: Dict[str, Any] = Field(
        default_factory=dict,
        description="Данные для применения действия (new state)",
    )
    backward_patch: Dict[str, Any] = Field(
        default_factory=dict,
        description="Данные для отмены действия (old state)",
    )

    # --- Группировка и флаги ---
    coalesce_key: Optional[str] = Field(
        default=None,
        description="Ключ группировки (тики слайдера → один Action)",
    )
    undoable: bool = Field(
        default=True,
        description="Можно ли отменить (False для COMMAND)",
    )

    # --- Описание и время ---
    description: str = Field(
        default="",
        description="Человекочитаемое описание действия",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Время создания (unix timestamp)",
    )
