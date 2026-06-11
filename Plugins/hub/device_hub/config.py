"""Конфиг DeviceHubPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import DeviceHubRegisters


@register_schema("DeviceHubPluginConfigV1")
class DeviceHubPluginConfig(PluginConfig):
    """Конфиг плагина device_hub — always-on хаб устройств."""

    plugin_class: str = "Plugins.hub.device_hub.plugin.DeviceHubPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [DeviceHubRegisters]

    # Дефолты (overrides из YAML)
    registry_path: str = "data/devices.yaml"
