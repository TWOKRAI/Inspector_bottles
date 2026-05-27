# -*- coding: utf-8 -*-
"""
Project — корневой агрегат domain-слоя.

Хранит текущую топологию (editor state) и slug активного рецепта.
active_recipe — строковый slug, не материализованный Recipe-объект.
Материализация рецепта выполняется adapter-ом в Phase C через RecipeStore.read(slug).

Метод apply() (Project → команда → новый Project + события) будет реализован
в Task B.4 (teamlead). В Task B.1 Project — только data-контейнер.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .topology import Topology


class Project(SchemaBase):
    """Корневой агрегат: текущая топология + активный рецепт (editor state).

    Project не хранит runtime-состояние (PID'ы, lifecycle, метрики).
    Runtime snapshot — отдельный aggregate, добавляется в Phase E/G.
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    topology: Annotated[Topology, FieldMeta("Текущая топология проекта (editor state)")]
    active_recipe: Annotated[
        str | None,
        FieldMeta("Slug активного рецепта (None — рецепт не выбран)"),
    ] = None

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать Project из словаря."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return self.model_dump(mode="json")
