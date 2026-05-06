"""Конфиг ChainExecutorPlugin — параметры цепочки шагов."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("ChainExecutorPluginConfigV1")
class ChainExecutorConfig(PluginConfig):
    """Конфиг плагина-оркестратора цепочки.

    Processing: items прогоняются через каждый шаг (sub-plugin) по порядку.
    Параллельный режим: каждый шаг получает копию items, результаты мержатся.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.chain_executor.plugin.ChainExecutorPlugin"
    )
    plugin_name: str = "chain_executor"
    category: str = "processing"

    # Шаги цепочки: [{"plugin_class": "full.path.Plugin", "plugin_name": "step_name", "config": {...}}]
    steps: list[dict] = []

    # Параллельный режим (каждый шаг получает копию items, результаты мержатся)
    parallel: bool = False

    # Максимальное число потоков для параллельного режима
    max_workers: int = 4

    # При ошибке в шаге: skip (продолжить) или fail (остановить)
    on_error: str = "skip"  # "skip" | "fail"
