# -*- coding: utf-8 -*-
"""
DisplayInstance — entity для привязки отображения к узлу топологии.

Связывает узел-источник (node_id) с конкретным дисплеем (display_id).
Адресация исключительно по display_id; имя дисплея резолвится из
DisplayRegistry / recipe.displays[].name по display_id.

Формат display_bindings (v3):
    YAML-рецепты используют ключи «node_id»/«display_id».
    Устаревший формат «source»/«display» больше НЕ принимается
    (extra='forbid' бросит ValidationError).
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase


class DisplayInstance(SchemaBase):
    """Привязка узла топологии к дисплею вывода."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    node_id: Annotated[str, FieldMeta("Идентификатор узла-источника (process.plugin.port или process.plugin)")]
    display_id: Annotated[str, FieldMeta("Идентификатор дисплея из DisplayRegistry")]

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать DisplayInstance из словаря (ожидает ключи node_id/display_id)."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return self.model_dump(mode="json")
