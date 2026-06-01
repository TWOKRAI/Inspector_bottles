"""Конфиг ContourFinderPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import ContourFinderRegisters


@register_schema("ContourFinderPluginConfigV1")
class ContourFinderPluginConfig(PluginConfig):
    """Конфиг плагина contour_finder."""

    plugin_class: str = "Plugins.processing.contour_finder.plugin.ContourFinderPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ContourFinderRegisters]
