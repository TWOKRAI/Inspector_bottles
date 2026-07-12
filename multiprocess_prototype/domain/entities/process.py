# -*- coding: utf-8 -*-
"""
Process — entity для одного процесса в топологии.

Агрегирует список плагинов (PluginInstance) и метаданные маршрутизации.
plugins хранится как tuple[PluginInstance, ...] для immutability.
chain_targets — кортеж имён процессов-получателей команд в chain-режиме.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import ConfigDict, Field, field_validator, model_validator
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .plugin import PluginInstance
from .worker import WorkerSpec

# Pipeline-routing shorthand-ключи framework-blueprint ProcessConfig (ADR-PM-014, рычаг
# C6a), которых НЕТ среди typed-полей домен-entity Process (chain_targets — уже typed-поле,
# роутинг не нужен). Домен их не типизирует, но ОБЯЗАН складывать в extras, а НЕ в metadata:
# framework читает их из typed-поля/extras (`as_generic_config._pick`,
# `infer_missing_inspectors`) и НИКОГДА из metadata. Поэтому shorthand-ключ, свёрнутый
# GUI round-trip'ом в metadata, для бэкенда нем — тихая деградация (явный
# `inspector: {mode: fanin}` теряет авторитетность → структурный join). См. ADR-PMM-017 п.5, AU-2.
_EXTRAS_SHORTHAND_KEYS: frozenset[str] = frozenset({"inspector", "source_target_fps", "io_peek"})


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
            "Passthrough-bag для runtime-телеметрии и прочих opaque-полей. "
            "Не интерпретируется domain-слоем — прозрачно передаётся adapter'ами. "
            "Pipeline-routing shorthand-ключи (inspector/source_target_fps/io_peek) сюда "
            "НЕ сворачиваются — они едут в extras (framework их из metadata не читает, AU-2)."
        ),
    )
    extras: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Domain-opaque мешок pipeline-routing ключей (inspector/source_target_fps/"
            "io_peek), которые framework-blueprint читает как typed-shorthand/extras "
            "(симметрия ProcessConfig.extras, ADR-PM-014). Escape-hatch inspector едет "
            "здесь и переживает GUI round-trip авторитетно; в metadata его "
            "infer_missing_inspectors игнорирует (ADR-PMM-017 п.5)."
        ),
    )

    # ------------------------------------------------------------------
    # Валидаторы: конвертируем list → tuple для совместимости с YAML
    # ------------------------------------------------------------------

    @model_validator(mode="before")
    @classmethod
    def _fold_extra_into_metadata(cls, data: Any) -> Any:
        """Свернуть плоские неизвестные поля процесса в ``extras``/``metadata``.

        Runnable-топологии и GUI-рецепты задают часть полей плоско. Domain-модель
        их не типизирует, но обязана сохранить БЕЗ ПОТЕРИ ДАННЫХ, чтобы редактор
        открывал любой pipeline, а сериализация переживала round-trip:
          - pipeline-routing shorthand-ключи (``_EXTRAS_SHORTHAND_KEYS``:
            inspector/source_target_fps/io_peek) → в ``extras`` (framework читает их
            только из typed-поля/extras, НЕ из metadata — AU-2, ADR-PMM-017 п.5);
          - прочие неизвестные ключи (телеметрия и пр.) → в ``metadata`` (passthrough).
        Явные ``extras``/``metadata`` во входе имеют приоритет над свёрнутыми
        одноимёнными ключами (симметрия conflict-warning ``ProcessConfig._pick``).
        """
        if not isinstance(data, dict):
            return data
        # known выводим из самой модели: при добавлении нового typed-поля в Process
        # его не нужно дублировать здесь (ключи model_fields == ключи YAML, без alias).
        known = set(cls.model_fields)
        unknown = {k: v for k, v in data.items() if k not in known}
        if not unknown:
            return data
        result = {k: v for k, v in data.items() if k in known}
        extras = dict(result.get("extras") or {})
        metadata = dict(result.get("metadata") or {})
        for key, value in unknown.items():
            bag = extras if key in _EXTRAS_SHORTHAND_KEYS else metadata
            if key in bag and bag[key] != value:
                # Явные extras/metadata имеют приоритет — предупреждаем о конфликте
                # с одноимённым плоским ключом (симметрия Fable LOW-5 в ProcessConfig).
                logger.warning(
                    "Process[{}]: плоский '{}'={!r} конфликтует с явным {}['{}']={!r} — "
                    "сохранено явное значение (приоритет).",
                    data.get("process_name", "?"),
                    key,
                    value,
                    "extras" if bag is extras else "metadata",
                    key,
                    bag[key],
                )
            bag.setdefault(key, value)
        if extras:
            result["extras"] = extras
        if metadata:
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
