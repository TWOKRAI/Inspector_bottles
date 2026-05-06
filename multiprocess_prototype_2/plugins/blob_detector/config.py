"""Конфиг BlobDetectorPlugin — параметры HSV-маски и фильтрации контуров."""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("BlobDetectorPluginConfigV1")
class BlobDetectorConfig(PluginConfig):
    """Конфиг плагина детекции цветных контуров.

    Processing: вход BGR → HSV-маска → findContours → detections + mask.
    Параметры изменяются runtime через set_color_range / set_area_range.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.blob_detector.plugin.BlobDetectorPlugin"
    )
    plugin_name: str = "blob_detector"
    category: str = "processing"

    # HSV-диапазон
    h_min: Annotated[int, FieldMeta(description="Hue minimum (0-180)")] = 0
    h_max: Annotated[int, FieldMeta(description="Hue maximum (0-180)")] = 180
    s_min: Annotated[int, FieldMeta(description="Saturation minimum (0-255)")] = 50
    s_max: Annotated[int, FieldMeta(description="Saturation maximum (0-255)")] = 255
    v_min: Annotated[int, FieldMeta(description="Value minimum (0-255)")] = 50
    v_max: Annotated[int, FieldMeta(description="Value maximum (0-255)")] = 255

    # Фильтрация по площади контура
    min_area: Annotated[int, FieldMeta(description="Минимальная площадь контура (px²)")] = 100
    max_area: Annotated[int, FieldMeta(description="Максимальная площадь (0 = без ограничения)")] = 0

    # Отрисовка контуров
    draw_contours: Annotated[bool, FieldMeta(description="Рисовать контуры на кадре")] = False
    contour_color_bgr: Annotated[
        list[int], FieldMeta(description="Цвет контуров BGR")
    ] = [0, 255, 0]
    contour_thickness: Annotated[int, FieldMeta(description="Толщина линий контуров")] = 2

    @property
    def memory(self) -> dict[str, Any] | None:
        """Не владеет SHM."""
        return None
