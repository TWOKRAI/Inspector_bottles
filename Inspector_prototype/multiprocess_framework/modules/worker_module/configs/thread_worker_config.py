# -*- coding: utf-8 -*-
"""ThreadWorkerConfig — плоская схема параметров потока-воркера (SchemaBase)."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("thread_worker")
class ThreadWorkerConfig(SchemaBase):
    """Параметры потока по смыслу ThreadConfig (dict at boundary через model_dump)."""

    priority: Annotated[
        Literal["SYSTEM", "REALTIME", "NORMAL", "BATCH", "BACKGROUND"],
        FieldMeta("Приоритет потока"),
    ] = "NORMAL"
    restart_on_failure: Annotated[bool, FieldMeta("Перезапуск при исключении")] = False
    max_restarts: Annotated[int, FieldMeta("Максимум автоперезапусков", min=0, max=100)] = 3
    dependencies: Annotated[list[str], FieldMeta("Имена воркеров-зависимостей")] = Field(
        default_factory=list
    )
    worker_type: Annotated[
        Literal["system", "application"],
        FieldMeta("Категория воркера"),
    ] = "application"
    execution_mode: Annotated[
        Literal["loop", "task"],
        FieldMeta("LOOP — цикл; TASK — одноразово"),
    ] = "loop"
