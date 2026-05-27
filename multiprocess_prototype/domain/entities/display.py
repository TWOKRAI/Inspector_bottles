# -*- coding: utf-8 -*-
"""
DisplayInstance — entity для привязки отображения к узлу топологии.

Связывает узел-источник (node_id) с конкретным дисплеем (display_id).
display_name — опциональная метка для UI.

Заметка о форматах display_bindings:
    Текущий live-формат в YAML-рецептах использует ключи «source»/«display»
    (не «node_id»/«display_id»). Нормализацию live-формата → entity выполняет
    Recipe.from_dict() через вспомогательный метод _normalize_display_binding().
    Подробнее — см. README пакета и комментарий в recipe.py.
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
    display_name: Annotated[str | None, FieldMeta("Отображаемое имя дисплея (для UI)")] = None

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
