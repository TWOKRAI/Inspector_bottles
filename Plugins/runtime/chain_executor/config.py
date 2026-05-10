"""Конфиг ChainExecutorPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import PluginConfig

from .registers import ChainExecutorRegisters


@register_schema("ChainExecutorPluginConfigV1")
class ChainExecutorConfig(PluginConfig):
    """Конфиг плагина-оркестратора цепочки — identity + register binding.

    Все параметры (steps, parallel, max_workers, on_error) — в ChainExecutorRegisters.
    """

    plugin_class: str = (
        "Plugins.runtime.chain_executor.plugin.ChainExecutorPlugin"
    )

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ChainExecutorRegisters]
