"""RenderOverlayRegisters — все параметры render_overlay плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase


@register_schema("RenderOverlayRegistersV1")
class RenderOverlayRegisters(SchemaBase):
    """Все параметры render_overlay — alpha blending маски + bounding boxes."""

    # Прозрачность маски
    mask_alpha: Annotated[float, FieldMeta(
        "Mask Alpha", info="Прозрачность маски (0.0-1.0)",
        min=0.0, max=1.0,
    )] = 0.5

    # Цвет маски (BGR)
    mask_color_b: Annotated[int, FieldMeta(
        "Mask Color B", info="Синий канал маски (0-255)",
        min=0, max=255,
    )] = 0
    mask_color_g: Annotated[int, FieldMeta(
        "Mask Color G", info="Зелёный канал маски (0-255)",
        min=0, max=255,
    )] = 255
    mask_color_r: Annotated[int, FieldMeta(
        "Mask Color R", info="Красный канал маски (0-255)",
        min=0, max=255,
    )] = 0

    # Отрисовка bounding boxes
    draw_detections: Annotated[bool, FieldMeta(
        "Draw Detections", info="Рисовать bounding boxes из detections",
    )] = True
    line_thickness: Annotated[int, FieldMeta(
        "Line Thickness", info="Толщина линий bounding box (px)",
        min=1, max=20,
    )] = 2
    label_font_scale: Annotated[float, FieldMeta(
        "Label Font Scale", info="Размер шрифта подписей bbox",
        min=0.1, max=5.0,
    )] = 0.5
