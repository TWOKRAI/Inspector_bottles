"""Конфиг TelemetrySinkPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import PluginConfig
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import register_schema

from .registers import TelemetrySinkRegisters


@register_schema("TelemetrySinkPluginConfigV1")
class TelemetrySinkPluginConfig(PluginConfig):
    """Конфиг стока телеметрии — identity + register binding.

    Все параметры (db_path, sample_interval_sec) — в TelemetrySinkRegisters.
    """

    plugin_class: str = "Plugins.io.telemetry_sink.plugin.TelemetrySinkPlugin"

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [TelemetrySinkRegisters]
