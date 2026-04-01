# -*- coding: utf-8 -*-
"""ThreadManagerConfig — схема параметров ThreadManager (QThread)."""
from __future__ import annotations

from typing import Annotated

from data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("frontend_thread_manager")
class ThreadManagerConfig(SchemaBase):
    """Дефолты для register() потоков."""

    manager_name: Annotated[str, FieldMeta("Логическое имя")] = "ThreadManager"
    default_stop_timeout_ms: Annotated[
        int,
        FieldMeta("Таймаут остановки потока, мс", min=100, max=120000),
    ] = 2000
    default_auto_start: Annotated[bool, FieldMeta("Автостарт новых потоков")] = True
