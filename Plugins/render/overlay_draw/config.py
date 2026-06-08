"""Конфиг OverlayDrawPlugin — identity + register_bindings."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import PluginConfig

from .registers import OverlayDrawRegisters


@register_schema("OverlayDrawPluginConfigV1")
class OverlayDrawConfig(PluginConfig):
    """Конфиг рисовальщика overlay — identity + register binding."""

    plugin_class: str = "Plugins.render.overlay_draw.plugin.OverlayDrawPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [OverlayDrawRegisters]
