"""Конфиг ColorMaskPlugin — параметры HSV-маски."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("ColorMaskPluginConfigV1")
class ColorMaskPluginConfig(PluginConfig):
    """Конфиг плагина цветовой маски.

    Простой processing-плагин: вход (frame) → cv2 HSV mask → выход (mask).
    """

    plugin_class: str = (
        "multiprocess_prototype.backend.plugins.color_mask.plugin.ColorMaskPlugin"
    )
    plugin_name: str = "color_mask"
    category: str = "processing"

    # Привязка к камере (для чтения SHM)
    camera_id: int = 0

    # HSV-диапазон для маски
    h_min: int = 0
    h_max: int = 180
    s_min: int = 50
    s_max: int = 255
    v_min: int = 50
    v_max: int = 255

    # Размеры для output SHM (должны совпадать с камерой)
    resolution_width: int = 640
    resolution_height: int = 480

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM для выходной маски (1 канал, grayscale)."""
        return {
            f"mask_{self.camera_id}": (self.resolution_height, self.resolution_width, 1),
            "coll": 1,
        }
