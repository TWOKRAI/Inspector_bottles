"""Конфиг RendererCompositorPlugin — identity + register_bindings.

V3_MY_PURE: все параметры живут в registers.py.
Config содержит только identity для discovery и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

from .registers import RendererCompositorRegisters


@register_schema("RendererCompositorPluginConfigV1")
class RendererCompositorConfig(PluginConfig):
    """Конфиг плагина compositing нескольких кадров — identity + register binding.

    Все параметры (layout, grid, pip, overlay) — в RendererCompositorRegisters.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.renderer_compositor.plugin.RendererCompositorPlugin"
    )
    plugin_name: str = "renderer_compositor"
    category: str = "processing"

    # Привязка к register-классам
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RendererCompositorRegisters]
