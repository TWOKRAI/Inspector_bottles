"""Конфиг PresenceWatchPlugin — register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import PresenceWatchRegisters


@register_schema("PresenceWatchPluginConfigV1")
class PresenceWatchPluginConfig(PluginConfig):
    """Конфиг плагина presence_watch."""

    plugin_class: str = "Plugins.processing.presence_watch.plugin.PresenceWatchPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [PresenceWatchRegisters]
