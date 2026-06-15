"""Конфиг BlobFilterPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import BlobFilterRegisters


@register_schema("BlobFilterPluginConfigV1")
class BlobFilterPluginConfig(PluginConfig):
    """Конфиг плагина blob_filter."""

    plugin_class: str = "Plugins.processing.blob_filter.plugin.BlobFilterPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [BlobFilterRegisters]
