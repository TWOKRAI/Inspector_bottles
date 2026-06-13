"""Конфиг CenterCropPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import PluginConfig
from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import SchemaBase

from .registers import CenterCropRegisters


@register_schema("CenterCropPluginConfigV1")
class CenterCropConfig(PluginConfig):
    """Конфиг плагина центрального crop — identity + register binding."""

    plugin_class: str = "Plugins.processing.center_crop.plugin.CenterCropPlugin"

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [CenterCropRegisters]
