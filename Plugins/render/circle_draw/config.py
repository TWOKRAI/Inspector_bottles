"""Конфиг CircleDrawPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import CircleDrawRegisters


@register_schema("CircleDrawPluginConfigV1")
class CircleDrawConfig(PluginConfig):
    """Конфиг плагина отрисовки окружностей — identity + register binding."""

    plugin_class: str = "Plugins.render.circle_draw.plugin.CircleDrawPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [CircleDrawRegisters]
