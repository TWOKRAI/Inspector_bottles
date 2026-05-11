# -*- coding: utf-8 -*-
"""
Action schema -- неизменяемая единица изменения состояния.

Action содержит forward_patch (apply) и backward_patch (revert),
что позволяет реализовать полноценный undo/redo.

coalesce_key -- ключ группировки: несколько Action с одинаковым ключом
(например, тики слайдера) объединяются в один при coalescing.

Наследуется от SchemaBase для автоматического маппинга полей
и совместимости с data_schema_module.

Конкретные типы action_type (enum) определяются в приложении,
фреймворк использует только str.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field, field_validator

from multiprocess_framework.modules.data_schema_module import SchemaBase


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
    action_type: str = Field(
        description="Тип действия (конкретные значения определяются приложением)",
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
        description="Ключ группировки (тики слайдера -> один Action)",
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

    # --- Валидация ---
    @field_validator("action_type")
    @classmethod
    def _action_type_not_empty(cls, v: str) -> str:
        """action_type не должен быть пустой строкой."""
        if not v or not v.strip():
            raise ValueError("action_type не может быть пустой строкой")
        return v
