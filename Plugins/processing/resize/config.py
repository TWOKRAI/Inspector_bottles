"""Конфиг ResizePlugin — параметры масштабирования."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import PluginConfig
from multiprocess_framework.modules.process_module.plugins import SchemaBase

from .registers import ResizeRegisters


@register_schema("ResizePluginConfigV2")
class ResizePluginConfig(PluginConfig):
    """Конфиг плагина масштабирования.

    Поддерживает два режима: scale_factor (относительный) или target_width/target_height (абсолютный).
    Runtime-параметры (scale_factor, target_*) вынесены в ResizeRegisters —
    register_bindings замыкает register_schema() плагина на live-обновления.
    """

    plugin_class: str = "Plugins.processing.resize.plugin.ResizePlugin"

    # Привязка к register-классам (источник для ProcessModulePlugin.register_schema)
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ResizeRegisters]

    # Привязка к камере
    camera_id: int = 0

    # Режим 1: относительное масштабирование
    scale_factor: float = 1.0

    # Режим 2: абсолютные размеры (приоритет над scale_factor если > 0)
    target_width: int = 0
    target_height: int = 0

    # Исходные размеры для расчёта output
    resolution_width: int = 640
    resolution_height: int = 480

    # Интерполяция: nearest, linear, cubic, area
    interpolation: str = "linear"

    # Routing
    frame_targets: list[str] | None = None
