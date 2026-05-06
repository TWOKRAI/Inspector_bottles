"""Конфиг WorkerPoolPlugin — параметры пула потоков."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("WorkerPoolPluginConfigV1")
class WorkerPoolConfig(PluginConfig):
    """Конфиг плагина параллельной обработки через пул потоков.

    Processing: items → ThreadPoolExecutor → sub-plugin → results.
    Каждый worker — отдельный экземпляр sub-plugin (thread safety).
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.worker_pool.plugin.WorkerPoolPlugin"
    )
    plugin_name: str = "worker_pool"
    category: str = "processing"

    # Размер пула потоков
    pool_size: int = 4

    # Таймаут ожидания результата от worker (секунды)
    queue_timeout: float = 5.0

    # Стратегия балансировки: "round_robin" | "shortest_queue"
    balancing: str = "round_robin"

    # Полный путь к классу плагина для worker'ов
    worker_plugin_class: str = ""

    # Конфиг для sub-plugin (передаётся как ctx.config)
    worker_plugin_config: dict = {}

    @property
    def memory(self) -> dict | None:
        """Нет SHM — worker pool работает in-process."""
        return None
