"""Конфиг EdgeDetectionPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import EdgeDetectionRegisters


@register_schema("EdgeDetectionPluginConfigV1")
class EdgeDetectionPluginConfig(PluginConfig):
    """Конфиг плагина edge_detection (TEED line-art)."""

    plugin_class: str = "Plugins.processing.edge_detection.plugin.EdgeDetectionPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [EdgeDetectionRegisters]
