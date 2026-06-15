"""Конфиг ImageAdjustPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import ImageAdjustRegisters


@register_schema("ImageAdjustPluginConfigV1")
class ImageAdjustPluginConfig(PluginConfig):
    """Конфиг плагина image_adjust."""

    plugin_class: str = "Plugins.processing.image_adjust.plugin.ImageAdjustPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ImageAdjustRegisters]
