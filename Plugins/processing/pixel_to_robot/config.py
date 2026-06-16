"""Конфиг PixelToRobotPlugin — register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import PixelToRobotRegisters


@register_schema("PixelToRobotPluginConfigV1")
class PixelToRobotPluginConfig(PluginConfig):
    """Конфиг плагина pixel_to_robot."""

    plugin_class: str = "Plugins.processing.pixel_to_robot.plugin.PixelToRobotPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [PixelToRobotRegisters]
