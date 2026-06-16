"""Конфиг CropPlugin — register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import CropRegisters


@register_schema("CropPluginConfigV1")
class CropPluginConfig(PluginConfig):
    """Конфиг плагина crop."""

    plugin_class: str = "Plugins.processing.crop.plugin.CropPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [CropRegisters]
