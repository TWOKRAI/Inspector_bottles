# -*- coding: utf-8 -*-
"""
ActionBuilder -- базовая фабрика для создания Action.

Содержит только generic core-методы:
- _make_id() -- генерация UUID
- field_set() -- изменение поля регистра с coalesce_key
- from_field() -- то же, но принимает RegisterBinding
- command() -- side-effect без undo

Все доменные методы (region_*, step_*, graph_*, topology_*,
display_*, layout_change, profile_switch, recipe_switch)
реализуются через наследование в приложении (AppActionBuilder).
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from .schemas import Action


@runtime_checkable
class RegisterBindingLike(Protocol):
    """Минимальный контракт RegisterBinding для ActionBuilder.from_field().

    Локальный Protocol вместо импорта frontend_module.schemas.register_binding —
    actions_module не должен знать про frontend_module (ADR-124 carve-out).
    Любой объект с двумя строковыми атрибутами совместим.
    """

    register_name: str
    field_name: str


class ActionBuilder:
    """Базовая фабрика Action. Расширяйте через наследование для domain-методов."""

    @staticmethod
    def _make_id() -> str:
        """Генерация уникального идентификатора."""
        return str(uuid.uuid4())

    @staticmethod
    def field_set(
        register_name: str,
        field_name: str,
        new_value: Any,
        old_value: Any,
        *,
        description: str = "",
    ) -> Action:
        """
        Создать Action для изменения поля регистра.

        coalesce_key формируется как "field:{register_name}.{field_name}",
        что позволяет группировать последовательные изменения одного поля
        (например, тики слайдера) в одно действие.
        """
        return Action(
            action_type="field_set",
            register_name=register_name,
            field_name=field_name,
            forward_patch={"value": new_value},
            backward_patch={"value": old_value},
            coalesce_key=f"field:{register_name}.{field_name}",
            undoable=True,
            description=description,
        )

    @staticmethod
    def from_field(
        binding: RegisterBindingLike,
        new_value: Any,
        old_value: Any,
        *,
        description: str = "",
    ) -> Action:
        """
        Создать Action из RegisterBinding-like объекта.

        Удобная обёртка над field_set() для случаев,
        когда привязка к регистру уже есть в виде RegisterBinding.
        """
        return ActionBuilder.field_set(
            register_name=binding.register_name,
            field_name=binding.field_name,
            new_value=new_value,
            old_value=old_value,
            description=description,
        )

    @staticmethod
    def command(description: str) -> Action:
        """
        Создать Action-команду (side-effect без undo).

        COMMAND не имеет forward/backward патчей и не может быть отменён.
        """
        return Action(
            action_type="command",
            undoable=False,
            description=description,
        )
