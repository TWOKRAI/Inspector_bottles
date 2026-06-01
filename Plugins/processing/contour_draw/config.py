"""Конфиг ContourDrawPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import ContourDrawRegisters


@register_schema("ContourDrawPluginConfigV1")
class ContourDrawPluginConfig(PluginConfig):
    """Конфиг плагина contour_draw."""

    plugin_class: str = "Plugins.processing.contour_draw.plugin.ContourDrawPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ContourDrawRegisters]
