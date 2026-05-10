"""Конфиг RenderOverlayPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

from .registers import RenderOverlayRegisters


@register_schema("RenderOverlayPluginConfigV1")
class RenderOverlayConfig(PluginConfig):
    """Конфиг плагина наложения маски — identity + register binding.

    Все параметры (alpha, color, detections) — в RenderOverlayRegisters.
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.render_overlay.plugin.RenderOverlayPlugin"
    )

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RenderOverlayRegisters]
