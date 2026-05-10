"""Конфиг ProcessorServicePlugin — параметры обработки."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("ProcessorServicePluginConfigV1")
class ProcessorServicePluginConfig(PluginConfig):
    """Конфиг плагина обработки кадров.

    Service-плагин: SHM receive (camera frame) → ProcessorService →
    SHM send (mask) → IPC (detection_result).
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.services.processor_service.plugin.ProcessorServicePlugin"
    )
    plugin_name: str = "processor"
    category: str = "processing"

    # Привязка к камере
    camera_id: int = 0

    # Детектор параметры
    color_lower: list[int] = [0, 0, 150]
    color_upper: list[int] = [100, 100, 255]
    min_area: int = 500
    max_area: int = 50000

    # Разрешение
    resolution_width: int = 640
    resolution_height: int = 480

    # ChainThreadPool
    workers_per_processor: int = 2
    step_timeout: float = 10.0

    # WorkerPoolDispatcher
    worker_pool_size: int = 0
    worker_timeout: float = 5.0
    worker_queue_size: int = 4

    # Каталог операций
    catalog_path: str = "data/processing_catalog.yaml"

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM для выходной маски."""
        return {
            f"processor_{self.camera_id}_mask": (
                self.resolution_height, self.resolution_width, 1
            ),
            "coll": 2,
        }
