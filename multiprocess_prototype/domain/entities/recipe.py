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

from pydantic import ConfigDict, Field, field_validator, model_validator
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .display import DisplayDefinition, DisplayInstance
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
    """Рецепт системы: blueprint топологии + активные сервисы + определения/привязки дисплеев."""

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
        FieldMeta(
            "Список активных сервисов (service_id). "
            "ЗАМОРОЖЕНО (RS-7, решение владельца 2026-07-13): резерв — пишется пустым "
            "при создании рецепта, GUI-редактирования нет; разморозка при появлении "
            "реального потребителя per-recipe сервисов"
        ),
    ] = ()
    displays: Annotated[
        tuple[DisplayDefinition, ...],
        FieldMeta("Определения дисплеев рецепта (SHM + render)"),
    ] = ()
    display_bindings: Annotated[
        tuple[DisplayInstance, ...],
        FieldMeta("Привязки узлов к дисплеям"),
    ] = ()
    devices: Annotated[
        tuple[dict[str, Any], ...],
        FieldMeta("Зарегистрированные устройства (top-level секция devices:, источник истины)"),
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

    @field_validator("displays", mode="before")
    @classmethod
    def _coerce_displays(cls, v: Any) -> tuple[DisplayDefinition, ...]:
        """Конвертирует list[dict] → tuple[DisplayDefinition, ...].

        Принимает list/tuple элементов: dict, DisplayDefinition или Pydantic-raw.
        """
        if isinstance(v, (list, tuple)):
            items: list[DisplayDefinition] = []
            for item in v:
                if isinstance(item, dict):
                    items.append(DisplayDefinition.from_dict(item))
                elif isinstance(item, DisplayDefinition):
                    items.append(item)
                else:
                    items.append(DisplayDefinition.model_validate(item))
            return tuple(items)
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

    @field_validator("devices", mode="before")
    @classmethod
    def _coerce_devices(cls, v: Any) -> tuple[dict[str, Any], ...]:
        """Конвертирует list[dict] → tuple[dict, ...] (raw-passthrough).

        Устройства имеют переменную форму (transport/params зависят от kind),
        поэтому хранятся как сырые dict'ы — их потребляют devices_sync/hub,
        а не строгая entity. Копируем dict, чтобы не делить ссылку с raw-yaml.
        """
        if isinstance(v, (list, tuple)):
            return tuple(dict(d) if isinstance(d, dict) else d for d in v)
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
    # Инварианты уровня рецепта (Task 1.2)
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate_recipe_invariants(self) -> "Recipe":
        """Проверяет инварианты целостности рецепта.

        1. Уникальность displays[].id в пределах рецепта.
        2. Каждый display_id в blueprint.displays присутствует в recipe.displays.
           Висячие ссылки (display_id без определения) → ValueError.

        Edge cases:
          - displays пуст + есть привязки → ошибка (висячие ссылки).
          - привязок нет → ok (дисплей без привязки допустим, раздел 6.6).
        """
        # 1. Уникальность id
        seen_ids: set[str] = set()
        for definition in self.displays:
            if definition.id in seen_ids:
                raise ValueError(f"Дубль display id: {definition.id}")
            seen_ids.add(definition.id)

        # 2. Валидация ссылок: blueprint.displays[].display_id ∈ seen_ids
        for binding in self.blueprint.displays:
            if binding.display_id not in seen_ids:
                raise ValueError(
                    f"Ссылка на несуществующий display_id: '{binding.display_id}' "
                    f"— определение отсутствует в секции displays рецепта"
                )

        return self

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
