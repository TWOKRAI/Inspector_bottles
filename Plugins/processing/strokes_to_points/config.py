"""Конфиг StrokesToPointsPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import StrokesToPointsRegisters


@register_schema("StrokesToPointsPluginConfigV1")
class StrokesToPointsPluginConfig(PluginConfig):
    """Конфиг плагина strokes_to_points."""

    plugin_class: str = "Plugins.processing.strokes_to_points.plugin.StrokesToPointsPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [StrokesToPointsRegisters]
