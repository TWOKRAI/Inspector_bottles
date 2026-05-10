"""Конфиг RenderOverlayPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import PluginConfig

from .registers import RenderOverlayRegisters


@register_schema("RenderOverlayPluginConfigV1")
class RenderOverlayConfig(PluginConfig):
    """Конфиг плагина наложения маски — identity + register binding.

    Все параметры (alpha, color, detections) — в RenderOverlayRegisters.
    """

    plugin_class: str = (
        "Plugins.render.render_overlay.plugin.RenderOverlayPlugin"
    )

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RenderOverlayRegisters]
