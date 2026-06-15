"""Конфиг SegmentationPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import SegmentationRegisters


@register_schema("SegmentationPluginConfigV1")
class SegmentationPluginConfig(PluginConfig):
    """Конфиг плагина segmentation."""

    plugin_class: str = "Plugins.processing.segmentation.plugin.SegmentationPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [SegmentationRegisters]
