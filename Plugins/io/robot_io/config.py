"""Конфиг RobotIoPlugin v2 — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import RobotIoRegisters


@register_schema("RobotIoPluginConfigV2")
class RobotIoPluginConfig(PluginConfig):
    """Конфиг плагина robot_io v2 — тонкий job-форвардер в devices."""

    plugin_class: str = "Plugins.io.robot_io.plugin.RobotIoPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RobotIoRegisters]

    # Привязка к устройству в реестре devices (override из YAML рецепта)
    device_id: str = "robot_main"
