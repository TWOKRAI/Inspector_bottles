"""WorkerPoolRegisters — все параметры worker_pool плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase


@register_schema("WorkerPoolRegistersV1")
class WorkerPoolRegisters(SchemaBase):
    """Все параметры worker_pool — пул потоков + sub-plugin конфиг."""

    # Размер пула потоков
    pool_size: Annotated[int, FieldMeta(
        "Pool Size", info="Размер пула потоков",
        min=1, max=64,
    )] = 4

    # Таймаут ожидания результата от worker
    queue_timeout: Annotated[float, FieldMeta(
        "Queue Timeout", info="Таймаут ожидания результата от worker", unit="s",
        min=0.1,
    )] = 5.0

    # Стратегия балансировки
    balancing: Annotated[str, FieldMeta(
        "Balancing", info='Стратегия балансировки: "round_robin" | "shortest_queue"',
    )] = "round_robin"

    # Полный путь к классу плагина для worker'ов
    worker_plugin_class: Annotated[str, FieldMeta(
        "Worker Plugin Class", info="Полный путь к классу плагина для worker'ов",
    )] = ""

    # Конфиг для sub-plugin
    worker_plugin_config: Annotated[dict, FieldMeta(
        "Worker Plugin Config", info="Конфиг для sub-plugin (передаётся как ctx.config)",
    )] = {}
