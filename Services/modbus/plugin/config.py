"""Конфиг ModbusPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py. Config содержит только identity
для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from Services.modbus.plugin.registers import ModbusRegisters


@register_schema("ModbusPluginConfigV1")
class ModbusPluginConfig(PluginConfig):
    """Конфиг плагина Modbus — identity + register binding."""

    plugin_class: str = "Services.modbus.plugin.plugin.ModbusPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [ModbusRegisters]
