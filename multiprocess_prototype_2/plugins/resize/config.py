"""Конфиг ResizePlugin — параметры масштабирования."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("ResizePluginConfigV2")
class ResizePluginConfig(PluginConfig):
    """Конфиг плагина масштабирования.

    Поддерживает два режима: scale_factor (относительный) или target_width/target_height (абсолютный).
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.resize.plugin.ResizePlugin"
    )
    plugin_name: str = "resize"
    category: str = "processing"

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

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM для выходного resized-кадра."""
        w, h = self._output_size()
        return {
            f"resized_{self.camera_id}": (h, w, 3),
            "coll": 1,
        }

    def _output_size(self) -> tuple[int, int]:
        """Вычислить output width, height."""
        if self.target_width > 0 and self.target_height > 0:
            return self.target_width, self.target_height
        w = int(self.resolution_width * self.scale_factor)
        h = int(self.resolution_height * self.scale_factor)
        return max(1, w), max(1, h)
