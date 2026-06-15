"""Конфиг PointsRenderPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import PointsRenderRegisters


@register_schema("PointsRenderPluginConfigV1")
class PointsRenderPluginConfig(PluginConfig):
    """Конфиг плагина points_render."""

    plugin_class: str = "Plugins.processing.points_render.plugin.PointsRenderPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [PointsRenderRegisters]
