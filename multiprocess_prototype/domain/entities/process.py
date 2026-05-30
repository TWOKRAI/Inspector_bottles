# -*- coding: utf-8 -*-
"""
Process — entity для одного процесса в топологии.

Агрегирует список плагинов (PluginInstance) и метаданные маршрутизации.
plugins хранится как tuple[PluginInstance, ...] для immutability.
chain_targets — кортеж имён процессов-получателей команд в chain-режиме.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .plugin import PluginInstance
from .worker import WorkerSpec


class Process(SchemaBase):
    """Типизированное описание процесса в топологии."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    process_name: Annotated[str, FieldMeta("Уникальное имя процесса в топологии")]
    plugins: Annotated[
        tuple[PluginInstance, ...],
        FieldMeta("Цепочка плагинов процесса (в порядке исполнения)"),
    ] = Field(default=())
    workers: Annotated[
        tuple[WorkerSpec, ...],
        FieldMeta("Воркеры (потоки) процесса — конфигурируемые сущности"),
    ] = Field(default=())
    process_class: Annotated[
        str | None,
        FieldMeta("Полный путь класса процесса (используется runtime-лоадером)"),
    ] = None
    priority: Annotated[
        str | None,
        FieldMeta("Приоритет процесса (normal, high, realtime)"),
    ] = None
    target_process: Annotated[
        str | None,
        FieldMeta("Имя целевого процесса для IPC-команд"),
    ] = None
    chain_targets: Annotated[
        tuple[str, ...],
        FieldMeta("Процессы-получатели в chain-топологии"),
    ] = ()
    description: Annotated[
        str | None,
        FieldMeta("Описание процесса (для UI и документации)"),
    ] = None
    protected: Annotated[
        bool,
        FieldMeta("Флаг защиты от удаления из GUI (например, gui-процесс)"),
    ] = False
    category: Annotated[
        str | None,
        FieldMeta("Категория процесса (для фильтрации в UI)"),
    ] = None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Passthrough-bag для runtime-полей (source_target_fps, телеметрия и пр.). "
            "Не интерпретируется domain-слоем — прозрачно передаётся adapter'ами."
        ),
    )

    # ------------------------------------------------------------------
    # Валидаторы: конвертируем list → tuple для совместимости с YAML
    # ------------------------------------------------------------------

    @model_validator(mode="before")
    @classmethod
    def _fold_extra_into_metadata(cls, data: Any) -> Any:
        """Свернуть плоские runtime-поля процесса в ``metadata``.

        Runnable-топологии задают runtime-поля плоско (``source_target_fps`` …).
        Domain-модель хранит их в ``metadata`` (passthrough). Сворачиваем без
        потери данных, чтобы редактор открывал любой runnable-pipeline.
        Явный ``metadata`` имеет приоритет.
        """
        if not isinstance(data, dict):
            return data
        # known выводим из самой модели: при добавлении нового поля в Process
        # его не нужно дублировать здесь, иначе оно молча уходило бы в metadata
        # (валидаторы без alias-полей — ключи model_fields == ключи YAML).
        known = set(cls.model_fields)
        extras = {k: v for k, v in data.items() if k not in known}
        if not extras:
            return data
        result = {k: v for k, v in data.items() if k in known}
        metadata = dict(result.get("metadata") or {})
        for key, value in extras.items():
            metadata.setdefault(key, value)
        result["metadata"] = metadata
        return result

    @field_validator("plugins", mode="before")
    @classmethod
    def _coerce_plugins_to_tuple(cls, v: Any) -> tuple[PluginInstance, ...]:
        """Преобразует list[dict | PluginInstance] → tuple[PluginInstance, ...].

        Нужно потому что YAML/JSON не различают tuple и list.
        """
        if isinstance(v, (list, tuple)):
            items: list[PluginInstance] = []
            for item in v:
                if isinstance(item, dict):
                    items.append(PluginInstance.from_dict(item))
                elif isinstance(item, PluginInstance):
                    items.append(item)
                else:
                    # Попытка валидации через Pydantic
                    items.append(PluginInstance.model_validate(item))
            return tuple(items)
        return v  # type: ignore[return-value]

    @field_validator("workers", mode="before")
    @classmethod
    def _coerce_workers_to_tuple(cls, v: Any) -> tuple[WorkerSpec, ...]:
        """Преобразует list[dict | WorkerSpec] → tuple[WorkerSpec, ...].

        Нужно потому что YAML/JSON не различают tuple и list.
        """
        if isinstance(v, (list, tuple)):
            items: list[WorkerSpec] = []
            for item in v:
                if isinstance(item, dict):
                    items.append(WorkerSpec.from_dict(item))
                elif isinstance(item, WorkerSpec):
                    items.append(item)
                else:
                    items.append(WorkerSpec.model_validate(item))
            return tuple(items)
        return v  # type: ignore[return-value]

    @field_validator("chain_targets", mode="before")
    @classmethod
    def _coerce_chain_targets_to_tuple(cls, v: Any) -> tuple[str, ...]:
        """Преобразует list → tuple для chain_targets."""
        if isinstance(v, list):
            return tuple(v)
        return v  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать Process из словаря (поддерживает list плагинов из YAML)."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (tuple → list для JSON/YAML совместимости)."""
        return self.model_dump(mode="json")
