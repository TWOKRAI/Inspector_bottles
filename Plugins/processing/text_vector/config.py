"""Конфиг TextVectorPlugin — register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import TextVectorRegisters


@register_schema("TextVectorPluginConfigV1")
class TextVectorPluginConfig(PluginConfig):
    """Конфиг плагина text_vector."""

    plugin_class: str = "Plugins.processing.text_vector.plugin.TextVectorPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [TextVectorRegisters]
