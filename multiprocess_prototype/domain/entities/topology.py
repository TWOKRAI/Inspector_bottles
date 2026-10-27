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

from pydantic import ConfigDict, Field, field_validator, model_serializer
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

    name: Annotated[
        str | None,
        FieldMeta("Имя блюпринта (как в файле рецепта); None — не задано, ключ в dict не пишется"),
    ] = None
    description: Annotated[
        str | None,
        FieldMeta("Описание блюпринта (как в файле рецепта); None — не задано, ключ в dict не пишется"),
    ] = None
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
    # Сериализатор: name/description=None не попадают в dict
    # ------------------------------------------------------------------

    @model_serializer(mode="wrap")
    def _drop_none_name_description(self, handler: Any) -> dict[str, Any]:
        """Убрать ``name``/``description``, если они ``None`` (design.md §4.2).

        Сериализатор модели, а не ``to_dict``: ``Recipe.to_dict()`` дампит вложенный
        ``Topology`` через ``model_dump`` мимо его ``to_dict``, и файл получил бы
        ``name: null``. Не ``exclude_none``: у процессов есть законные ``null``.
        """
        data = handler(self)
        for key in ("name", "description"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

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
    # Structural query helpers (Task B.4)
    # ------------------------------------------------------------------

    def find_process(self, name: str) -> Process | None:
        """Найти процесс по имени. Возвращает None если не найден."""
        for proc in self.processes:
            if proc.process_name == name:
                return proc
        return None

    def find_wires_for(self, process_name: str) -> tuple[Wire, ...]:
        """Найти все wires, связанные с данным процессом.

        Wire считается связанным, если первый сегмент source или target
        (по точке) совпадает с process_name.
        """
        result: list[Wire] = []
        for wire in self.wires:
            src_proc = wire.source.split(".")[0]
            tgt_proc = wire.target.split(".")[0]
            if src_proc == process_name or tgt_proc == process_name:
                result.append(wire)
        return tuple(result)

    def find_display_bindings_for(self, process_name: str) -> tuple[DisplayInstance, ...]:
        """Найти все display bindings, связанные с данным процессом.

        DisplayInstance считается связанным, если первый сегмент node_id
        (по точке) совпадает с process_name.
        """
        result: list[DisplayInstance] = []
        for di in self.displays:
            node_proc = di.node_id.split(".")[0]
            if node_proc == process_name:
                result.append(di)
        return tuple(result)

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать Topology из словаря.

        ``name`` и ``description`` — типизированные поля ``Topology`` и в ``metadata`` не
        переносятся (изменение поведения ``topology.apply``: он несёт имя блюпринта из файла,
        а не умолчание ``"default"``; design.md §4.2). В ``metadata`` перемещается только
        ``display_definitions`` (приходит из ``merge_topologies``) — whitelist защищает от
        молчаливого поглощения опечаток (extra='forbid' сработает корректно).
        """
        known_keys = {"processes", "wires", "displays", "metadata", "name", "description"}
        # Whitelist: display_definitions проброшен через merge_topologies (Task 1.1/2.2) —
        # не относится к Topology domain-модели, но приходит в том же dict.
        _BLUEPRINT_META_KEYS: frozenset[str] = frozenset({"display_definitions"})

        extra_keys = set(data.keys()) - known_keys
        if not extra_keys:
            return cls.model_validate(data)

        unexpected = extra_keys - _BLUEPRINT_META_KEYS
        if unexpected:
            # Неизвестные ключи вне whitelist — передаём как есть,
            # чтобы extra="forbid" поднял ValidationError
            return cls.model_validate(data)

        # Перемещаем только whitelisted мета-поле в metadata
        data = dict(data)
        meta = dict(data.get("metadata") or {})
        for key in _BLUEPRINT_META_KEYS & extra_keys:
            meta[key] = data.pop(key)
        data["metadata"] = meta
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (tuple → list для JSON/YAML совместимости)."""
        return self.model_dump(mode="json")
