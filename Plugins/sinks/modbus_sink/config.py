"""Конфиг ModbusSinkPlugin — identity + register binding.

config_class() плагина возвращает этот класс → register_schema() резолвит
register_bindings, RegistersManager процесса создаётся, handler register_update
регистрируется (live-правка host/port/base_address из GUI).
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import ModbusSinkRegisters


@register_schema("ModbusSinkPluginConfigV1")
class ModbusSinkPluginConfig(PluginConfig):
    """Конфиг плагина modbus_sink — вывод метаданных кадра по Modbus."""

    plugin_class: str = "Plugins.sinks.modbus_sink.plugin.ModbusSinkPlugin"

    # Привязка к register-классам (источник для ProcessModulePlugin.register_schema)
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ModbusSinkRegisters]

    # Дефолты подключения/записи (дублируют register для overrides из YAML)
    transport: str = "tcp"
    host: str = "127.0.0.1"
    port: int = 5020
    unit_id: int = 1
    base_address: int = 100
    write_every_n: int = 1
    auto_connect: bool = True
