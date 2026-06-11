"""Конфиг VfdControlPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import VfdControlRegisters


@register_schema("VfdControlPluginConfigV1")
class VfdControlPluginConfig(PluginConfig):
    """Конфиг плагина vfd_control — ПЧ через мост робота."""

    plugin_class: str = "Plugins.control.vfd_control.plugin.VfdControlPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [VfdControlRegisters]

    freq_max_hz: float = 50.0
    default_freq_hz: float = 10.0
    poll_interval_s: float = 0.5
