# -*- coding: utf-8 -*-
"""
RecipeMeta и Recipe — entities для рецептов системы.

RecipeMeta хранит метаданные рецепта (имя, версия, дата создания).
Recipe агрегирует meta + blueprint (Topology) + активные сервисы + привязки дисплеев.

Формат display_bindings (v3):
    display_bindings:
      - node_id: merge_proc.render_overlay.rendered_frame
        display_id: main_output
    Единственный принимаемый формат — «node_id»/«display_id».
    Устаревший формат «source»/«display» больше НЕ принимается
    (DisplayInstance extra='forbid' бросит ValidationError).

    gui_positions в YAML хранится как dict[str, [x, y]] (list из двух float).
    from_dict() конвертирует list[float, float] → tuple[float, float].
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, field_validator
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .display import DisplayInstance
from .topology import Topology


class RecipeMeta(SchemaBase):
    """Метаданные рецепта."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    name: Annotated[str, FieldMeta("Уникальное имя рецепта (slug)")]
    version: Annotated[int, FieldMeta("Версия формата рецепта")] = 3
    description: Annotated[str, FieldMeta("Описание рецепта")] = ""
    created_at: Annotated[str, FieldMeta("Дата создания (ISO 8601)")] = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать RecipeMeta из словаря."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return self.model_dump(mode="json")


class Recipe(SchemaBase):
    """Рецепт системы: blueprint топологии + активные сервисы + привязки дисплеев."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    meta: Annotated[RecipeMeta, FieldMeta("Метаданные рецепта")]
    blueprint: Annotated[Topology, FieldMeta("Топология (blueprint) рецепта")] = Field(
        default_factory=lambda: Topology(),
    )
    active_services: Annotated[
        tuple[str, ...],
        FieldMeta("Список активных сервисов (service_id)"),
    ] = ()
    display_bindings: Annotated[
        tuple[DisplayInstance, ...],
        FieldMeta("Привязки узлов к дисплеям"),
    ] = ()
    gui_positions: dict[str, tuple[float, float]] = Field(
        default_factory=dict,
        description="Позиции узлов в GUI-редакторе: node_id → (x, y).",
    )

    @field_validator("blueprint", mode="before")
    @classmethod
    def _normalize_blueprint(cls, v: Any) -> Any:
        """Нормализует blueprint: передаёт dict через Topology.from_dict.

        Topology.from_dict перемещает неизвестные ключи (name, description)
        в metadata, чтобы не нарушать extra='forbid'.
        """
        if isinstance(v, dict):
            return Topology.from_dict(v)
        return v

    @field_validator("active_services", mode="before")
    @classmethod
    def _coerce_active_services(cls, v: Any) -> tuple[str, ...]:
        """Конвертирует list → tuple."""
        if isinstance(v, list):
            return tuple(v)
        return v  # type: ignore[return-value]

    @field_validator("display_bindings", mode="before")
    @classmethod
    def _coerce_display_bindings(cls, v: Any) -> tuple[DisplayInstance, ...]:
        """Конвертирует list[dict] → tuple[DisplayInstance, ...].

        Принимает только формат v3: {"node_id": ..., "display_id": ...}.
        Устаревший формат {"source": ..., "display": ...} вызовет
        ValidationError (DisplayInstance extra='forbid').
        """
        if isinstance(v, (list, tuple)):
            items: list[DisplayInstance] = []
            for item in v:
                if isinstance(item, dict):
                    items.append(DisplayInstance.from_dict(item))
                elif isinstance(item, DisplayInstance):
                    items.append(item)
                else:
                    items.append(DisplayInstance.model_validate(item))
            return tuple(items)
        return v  # type: ignore[return-value]

    @field_validator("gui_positions", mode="before")
    @classmethod
    def _coerce_gui_positions(cls, v: Any) -> dict[str, tuple[float, float]]:
        """Конвертирует dict[str, list[float, float]] → dict[str, tuple[float, float]]."""
        if isinstance(v, dict):
            result: dict[str, tuple[float, float]] = {}
            for key, val in v.items():
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    result[key] = (float(val[0]), float(val[1]))
                else:
                    result[key] = val  # type: ignore[assignment]
            return result
        return v  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать Recipe из словаря.

        display_bindings принимает только формат v3 (node_id/display_id).
        Устаревший формат source/display НЕ поддерживается — вызовет
        ValidationError через DisplayInstance(extra='forbid').

        Автоматически строит RecipeMeta из полей верхнего уровня,
        если поле 'meta' отсутствует.

        Формат рецептов v3 (YAML):
            name: <slug>
            version: 3
            description: ...
            blueprint:
              name: ...       ← мета blueprint, перемещается в Topology.metadata
              description: ...
              processes: [...]
              wires: [...]
        """
        data = dict(data)

        # Шаг 1: Если нет 'meta' — строим из полей верхнего уровня
        if "meta" not in data:
            meta_fields: dict[str, Any] = {}
            for field in ("name", "version", "description", "created_at"):
                if field in data:
                    meta_fields[field] = data[field]
            if meta_fields:
                data["meta"] = meta_fields

        # Шаг 2: Удаляем поля верхнего уровня, которые вошли в meta
        # (иначе extra="forbid" запретит их)
        for field in ("name", "version", "description", "created_at"):
            data.pop(field, None)

        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (tuple → list, tuple[float,float] → list)."""
        return self.model_dump(mode="json")
