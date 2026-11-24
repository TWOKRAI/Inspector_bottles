"""Конфиг FrameBufferPlugin — identity + register_bindings.

Purpose: identity для discovery и привязка к register-классу; параметры живут в registers.py.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import PluginConfig, SchemaBase, register_schema

from .registers import FrameBufferRegisters

__all__ = ["FrameBufferPluginConfig"]


@register_schema("FrameBufferPluginConfigV1")
class FrameBufferPluginConfig(PluginConfig):
    """Конфиг плагина буфера кадров — identity + register binding."""

    plugin_class: str = "Plugins.io.frame_buffer.plugin.FrameBufferPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [FrameBufferRegisters]
