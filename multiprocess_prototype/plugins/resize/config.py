"""Конфиг ResizePlugin — параметры масштабирования."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("ResizePluginConfigV2")
class ResizePluginConfig(PluginConfig):
    """Конфиг плагина масштабирования.

    Поддерживает два режима: scale_factor (относительный) или target_width/target_height (абсолютный).
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.resize.plugin.ResizePlugin"
    )

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
