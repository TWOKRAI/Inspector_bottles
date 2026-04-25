# -*- coding: utf-8 -*-
"""WorkerManagerConfig — конфигурация WorkerManager с вложенным ThreadWorkerConfig."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from .thread_worker_config import ThreadWorkerConfig


@register_schema("worker_manager")
class WorkerManagerConfig(SchemaBase):
    """Конфигурация WorkerManager."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "WorkerManager"
    thread: Annotated[
        ThreadWorkerConfig,
        FieldMeta("Параметры потока по умолчанию"),
    ] = Field(default_factory=ThreadWorkerConfig)
