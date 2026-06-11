"""Конфиг RobotIoPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import RobotIoRegisters


@register_schema("RobotIoPluginConfigV1")
class RobotIoPluginConfig(PluginConfig):
    """Конфиг плагина robot_io — владелец соединения с роботом."""

    plugin_class: str = "Plugins.io.robot_io.plugin.RobotIoPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RobotIoRegisters]

    # Дефолты подключения (overrides из YAML)
    host: str = "192.168.1.7"
    port: int = 502
    unit_id: int = 2
    word_order: str = "little"
    auto_connect: bool = True
