"""Конфиг RobotScalePlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import RobotScaleRegisters


@register_schema("RobotScalePluginConfigV1")
class RobotScalePluginConfig(PluginConfig):
    """Конфиг плагина robot_scale."""

    plugin_class: str = "Plugins.processing.robot_scale.plugin.RobotScalePlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RobotScaleRegisters]
