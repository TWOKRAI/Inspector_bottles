"""Конфиг WordLayoutPlugin — register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import WordLayoutRegisters


@register_schema("WordLayoutPluginConfigV1")
class WordLayoutPluginConfig(PluginConfig):
    """Конфиг плагина word_layout."""

    plugin_class: str = "Plugins.processing.word_layout.plugin.WordLayoutPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [WordLayoutRegisters]
