# -*- coding: utf-8 -*-
"""
Topology — entity для топологии системы.

Агрегирует все процессы, провода и привязки дисплеев.
Поля processes, wires, displays — tuple для immutability.
metadata — dict для произвольных расширений (gui_positions и т.п.),
не интерпретируется domain-слоем.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, field_validator
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .display import DisplayInstance
from .process import Process
from .wire import Wire


class Topology(SchemaBase):
    """Полное описание топологии системы (editor state, не runtime state)."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    processes: Annotated[
        tuple[Process, ...],
        FieldMeta("Список процессов в топологии"),
    ] = ()
    wires: Annotated[
        tuple[Wire, ...],
        FieldMeta("Соединения между узлами"),
    ] = ()
    displays: Annotated[
        tuple[DisplayInstance, ...],
        FieldMeta("Привязки дисплеев к узлам"),
    ] = ()
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Метаданные топологии (gui_positions, etc.). Не интерпретируется domain.",
    )

    # ------------------------------------------------------------------
    # Валидаторы: конвертируем list → tuple для совместимости с YAML
    # ------------------------------------------------------------------

    @field_validator("processes", mode="before")
    @classmethod
    def _coerce_processes_to_tuple(cls, v: Any) -> tuple[Process, ...]:
        """Конвертирует list[dict | Process] → tuple[Process, ...]."""
        if isinstance(v, (list, tuple)):
            items: list[Process] = []
            for item in v:
                if isinstance(item, dict):
                    items.append(Process.from_dict(item))
                elif isinstance(item, Process):
                    items.append(item)
                else:
                    items.append(Process.model_validate(item))
            return tuple(items)
        return v  # type: ignore[return-value]

    @field_validator("wires", mode="before")
    @classmethod
    def _coerce_wires_to_tuple(cls, v: Any) -> tuple[Wire, ...]:
        """Конвертирует list[dict | Wire] → tuple[Wire, ...]."""
        if isinstance(v, (list, tuple)):
            items: list[Wire] = []
            for item in v:
                if isinstance(item, dict):
                    items.append(Wire.from_dict(item))
                elif isinstance(item, Wire):
                    items.append(item)
                else:
                    items.append(Wire.model_validate(item))
            return tuple(items)
        return v  # type: ignore[return-value]

    @field_validator("displays", mode="before")
    @classmethod
    def _coerce_displays_to_tuple(cls, v: Any) -> tuple[DisplayInstance, ...]:
        """Конвертирует list[dict | DisplayInstance] → tuple[DisplayInstance, ...]."""
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

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать Topology из словаря.

        Поддерживает SystemBlueprint-формат, где на верхнем уровне
        могут присутствовать поля «name» и «description» (мета-поля blueprint).
        Эти поля помещаются в metadata['name'] / metadata['description'],
        чтобы не нарушать extra='forbid'.
        """
        known_keys = {"processes", "wires", "displays", "metadata"}
        extra_keys = set(data.keys()) - known_keys
        if extra_keys:
            # Перемещаем неизвестные ключи в metadata
            data = dict(data)
            meta = dict(data.get("metadata", {}))
            for key in extra_keys:
                meta[key] = data.pop(key)
            data["metadata"] = meta
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (tuple → list для JSON/YAML совместимости)."""
        return self.model_dump(mode="json")
