"""Конфиг RenderOverlayPlugin — параметры наложения маски и bounding boxes."""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("RenderOverlayPluginConfigV1")
class RenderOverlayConfig(PluginConfig):
    """Конфиг плагина наложения маски.

    Processing: вход frame + mask (опц.) + detections (опц.) → rendered_frame.
    Параметры изменяются runtime через команды set_alpha, set_color, toggle_detections.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.render_overlay.plugin.RenderOverlayPlugin"
    )
    plugin_name: str = "render_overlay"
    category: str = "processing"

    # Прозрачность маски
    mask_alpha: Annotated[
        float, FieldMeta(description="Прозрачность маски (0.0-1.0)")
    ] = 0.5

    # Цвет маски (BGR)
    mask_color_b: Annotated[
        int, FieldMeta(description="Синий канал маски (0-255)")
    ] = 0
    mask_color_g: Annotated[
        int, FieldMeta(description="Зелёный канал маски (0-255)")
    ] = 255
    mask_color_r: Annotated[
        int, FieldMeta(description="Красный канал маски (0-255)")
    ] = 0

    # Отрисовка bounding boxes
    draw_detections: Annotated[
        bool, FieldMeta(description="Рисовать bounding boxes из detections")
    ] = True
    line_thickness: Annotated[
        int, FieldMeta(description="Толщина линий bounding box (px)")
    ] = 2
    label_font_scale: Annotated[
        float, FieldMeta(description="Размер шрифта подписей bbox")
    ] = 0.5

    @property
    def memory(self) -> None:
        """SHM не используется — плагин работает только внутри pipeline."""
        return None
