"""Конфиг WorkerPoolPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

from .registers import WorkerPoolRegisters


@register_schema("WorkerPoolPluginConfigV1")
class WorkerPoolConfig(PluginConfig):
    """Конфиг плагина параллельной обработки через пул потоков — identity + register binding.

    Все параметры (pool_size, queue_timeout, balancing, worker_plugin_class/config) — в WorkerPoolRegisters.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.worker_pool.plugin.WorkerPoolPlugin"
    )

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [WorkerPoolRegisters]
