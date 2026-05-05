"""Конфиг ColorMaskPlugin — параметры HSV-маски."""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("ColorMaskPluginConfigV2Proto2")
class ColorMaskPluginConfig(PluginConfig):
    """Конфиг плагина цветовой маски.

    Processing: вход BGR → cv2 HSV inRange → выход mask.
    Пороги изменяются runtime через set_hsv_range.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.color_mask.plugin.ColorMaskPlugin"
    )
    plugin_name: str = "color_mask"
    category: str = "processing"

    # Привязка к камере
    camera_id: Annotated[
        int, FieldMeta(description="ID камеры (для SHM-имён)")
    ] = 0

    # HSV-диапазон
    h_min: Annotated[int, FieldMeta(description="Hue minimum (0-180)")] = 0
    h_max: Annotated[int, FieldMeta(description="Hue maximum (0-180)")] = 180
    s_min: Annotated[int, FieldMeta(description="Saturation minimum (0-255)")] = 50
    s_max: Annotated[int, FieldMeta(description="Saturation maximum (0-255)")] = 255
    v_min: Annotated[int, FieldMeta(description="Value minimum (0-255)")] = 50
    v_max: Annotated[int, FieldMeta(description="Value maximum (0-255)")] = 255

    # Размеры для output SHM
    resolution_width: Annotated[
        int, FieldMeta(description="Ширина кадра (px)")
    ] = 640
    resolution_height: Annotated[
        int, FieldMeta(description="Высота кадра (px)")
    ] = 480

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM для выходной маски (1 канал)."""
        return {
            f"mask_{self.camera_id}": (self.resolution_height, self.resolution_width, 1),
            "coll": 1,
        }
