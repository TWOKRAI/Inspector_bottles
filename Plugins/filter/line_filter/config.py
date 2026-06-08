"""Конфиг LineFilterPlugin — identity + register_bindings.

Все параметры — в registers.py. Config содержит только identity для discovery
и привязку к register-классам.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import PluginConfig

from .registers import LineFilterRegisters


@register_schema("LineFilterPluginConfigV1")
class LineFilterConfig(PluginConfig):
    """Конфиг фильтра виртуальной линии — identity + register binding."""

    plugin_class: str = "Plugins.filter.line_filter.plugin.LineFilterPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [LineFilterRegisters]
