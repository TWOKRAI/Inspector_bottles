"""Конфиг ProcessorWorkerPlugin — параметры воркера пула."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("ProcessorWorkerPluginConfigV1")
class ProcessorWorkerPluginConfig(PluginConfig):
    """Конфиг плагина воркера пула обработки.

    Service-плагин: получает задачи от Processor → выполняет операцию →
    возвращает результат через IPC.
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.services.processor_worker.plugin.ProcessorWorkerPlugin"
    )
    plugin_name: str = "processor_worker"
    category: str = "service"

    # Идентификация воркера
    worker_index: int = 0
    process_id: str = ""

    # Каталог операций
    catalog_path: str = "data/processing_catalog.yaml"
