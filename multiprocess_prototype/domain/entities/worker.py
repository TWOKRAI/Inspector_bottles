# -*- coding: utf-8 -*-
"""
WorkerSpec — entity для одного воркера (потока) внутри Process.

Воркер — конфигурируемая сущность: имя, приоритет потока, режим исполнения и
целевой интервал цикла. Полезную нагрузку воркер получает позже (Pipeline);
здесь хранится только декларативная конфигурация для спавна через WorkerManager.

worker_class — dotted-path класса воркера (target callable = instance.run). None
означает generic IdleWorker (loop со smart-sleep, без нагрузки). config — passthrough
dict (как PluginInstance.config), не интерпретируется domain-слоем.

protected=True помечает дефолтный системный воркер (message_processor —
опрашивает RouterManager для IPC). Такой воркер нельзя удалить/остановить из GUI.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

# Приоритеты потока (совпадают с ThreadConfig фреймворка → poll_interval).
WorkerPriority = Literal["SYSTEM", "REALTIME", "NORMAL", "BATCH", "BACKGROUND"]
# Режим исполнения: LOOP — бесконечный цикл; TASK — одноразовый проход.
WorkerExecutionMode = Literal["loop", "task"]


class WorkerSpec(SchemaBase):
    """Описывает один воркер (поток) внутри Process."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
        # validate_assignment теряет смысл при frozen=True
    )

    worker_name: Annotated[str, FieldMeta("Уникальное имя воркера в процессе")]
    priority: Annotated[
        WorkerPriority,
        FieldMeta("Приоритет потока (SYSTEM/REALTIME/NORMAL/BATCH/BACKGROUND)"),
    ] = "NORMAL"
    execution_mode: Annotated[
        WorkerExecutionMode,
        FieldMeta("LOOP — цикл; TASK — одноразово"),
    ] = "loop"
    target_interval_ms: Annotated[
        int | None,
        FieldMeta("Целевой интервал цикла в мс (smart sleep). None — по приоритету"),
    ] = None
    worker_class: Annotated[
        str | None,
        FieldMeta("Полный путь класса воркера (None → generic IdleWorker)"),
    ] = None
    protected: Annotated[
        bool,
        FieldMeta("Флаг защиты (системный воркер, неудаляем/неостанавливаем из GUI)"),
    ] = False
    description: Annotated[
        str | None,
        FieldMeta("Описание воркера (для UI и документации)"),
    ] = None
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Конфигурация воркера (passthrough, нагрузку даёт Pipeline).",
    )

    @model_validator(mode="before")
    @classmethod
    def _fold_extra_into_config(cls, data: Any) -> Any:
        """Свернуть плоские неизвестные поля воркера в ``config`` (passthrough).

        По образцу PluginInstance._fold_extra_into_config — runnable-форматы могут
        задавать параметры воркера плоско. Известные поля выводим из model_fields,
        чтобы не хардкодить список. Явный ``config`` имеет приоритет.
        """
        if not isinstance(data, dict):
            return data
        known = set(cls.model_fields)
        extras = {k: v for k, v in data.items() if k not in known}
        if not extras:
            return data
        result = {k: v for k, v in data.items() if k in known}
        config = dict(result.get("config") or {})
        for key, value in extras.items():
            config.setdefault(key, value)
        result["config"] = config
        return result

    # ------------------------------------------------------------------
    # Сериализация (тонкие обёртки для читаемости в presenter-ах)
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать WorkerSpec из словаря."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (mode='json': tuple→list, datetime→str)."""
        return self.model_dump(mode="json")
