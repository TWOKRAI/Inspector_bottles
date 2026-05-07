"""Конфиг ColorMaskPlugin — identity + register_bindings.

V3_MY_PURE: все параметры (HSV, camera_id, resolution) живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

from .registers import ColorMaskRegisters


@register_schema("ColorMaskPluginConfigV2Proto2")
class ColorMaskPluginConfig(PluginConfig):
    """Конфиг плагина цветовой маски — identity + register binding.

    Все параметры (camera_id, HSV, resolution) — в ColorMaskRegisters.
    YAML-поля попадают в __pydantic_extra__ (extra="allow") и
    проксируются в register через from_plugins() memory proxy.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.color_mask.plugin.ColorMaskPlugin"
    )
    plugin_name: str = "color_mask"
    category: str = "processing"

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ColorMaskRegisters]
