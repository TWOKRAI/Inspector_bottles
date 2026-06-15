"""Конфиг RobotDrawPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import RobotDrawRegisters


@register_schema("RobotDrawPluginConfigV1")
class RobotDrawPluginConfig(PluginConfig):
    """Конфиг плагина robot_draw — форвардер точек рисования в devices."""

    plugin_class: str = "Plugins.io.robot_draw.plugin.RobotDrawPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RobotDrawRegisters]

    # Привязка к устройству в реестре devices (override из YAML рецепта)
    device_id: str = "robot_main"
