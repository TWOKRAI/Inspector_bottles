"""Конфиг DrawingIoPlugin — register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import DrawingIoRegisters


@register_schema("DrawingIoPluginConfigV1")
class DrawingIoPluginConfig(PluginConfig):
    """Конфиг плагина drawing_io."""

    plugin_class: str = "Plugins.io.drawing_io.plugin.DrawingIoPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [DrawingIoRegisters]
