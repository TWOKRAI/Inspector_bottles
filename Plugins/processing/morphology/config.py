"""Конфиг MorphologyPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import MorphologyRegisters


@register_schema("MorphologyPluginConfigV1")
class MorphologyPluginConfig(PluginConfig):
    """Конфиг плагина morphology."""

    plugin_class: str = "Plugins.processing.morphology.plugin.MorphologyPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [MorphologyRegisters]
