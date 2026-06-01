"""Конфиг HsvMaskPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import HsvMaskRegisters


@register_schema("HsvMaskPluginConfigV1")
class HsvMaskPluginConfig(PluginConfig):
    """Конфиг плагина hsv_mask."""

    plugin_class: str = "Plugins.processing.hsv_mask.plugin.HsvMaskPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [HsvMaskRegisters]
