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
    """Конфиг плагина robot_draw — рисование фигур роботом."""

    plugin_class: str = "Plugins.control.robot_draw.plugin.RobotDrawPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RobotDrawRegisters]

    pen_down_mm: float = 0.0
    pen_up_mm: float = 10.0
    draw_speed_pct: int = 30
    auto_draw: bool = False
