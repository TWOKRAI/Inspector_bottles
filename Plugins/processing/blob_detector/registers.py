"""BlobDetectorRegisters — все параметры blob_detector плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("BlobDetectorRegistersV1")
class BlobDetectorRegisters(SchemaBase):
    """Все параметры blob_detector — HSV-фильтрация + area + отрисовка контуров."""

    # HSV-диапазон
    h_min: Annotated[int, FieldMeta(
        "Min Hue", info="Нижняя граница H (0-180)",
        min=0, max=180, unit="°",
    )] = 0
    h_max: Annotated[int, FieldMeta(
        "Max Hue", info="Верхняя граница H (0-180)",
        min=0, max=180, unit="°",
    )] = 180
    s_min: Annotated[int, FieldMeta(
        "Min Saturation", info="Нижняя граница S",
        min=0, max=255,
    )] = 50
    s_max: Annotated[int, FieldMeta(
        "Max Saturation", info="Верхняя граница S",
        min=0, max=255,
    )] = 255
    v_min: Annotated[int, FieldMeta(
        "Min Value", info="Нижняя граница V",
        min=0, max=255,
    )] = 50
    v_max: Annotated[int, FieldMeta(
        "Max Value", info="Верхняя граница V",
        min=0, max=255,
    )] = 255

    # Фильтрация по площади контура
    min_area: Annotated[int, FieldMeta(
        "Min Area", info="Минимальная площадь контура (px²)", min=0,
    )] = 100
    max_area: Annotated[int, FieldMeta(
        "Max Area", info="Максимальная площадь (0 = без ограничения)", min=0,
    )] = 0

    # Отрисовка контуров
    draw_contours: Annotated[bool, FieldMeta(
        "Draw Contours", info="Рисовать контуры на кадре",
    )] = False
    contour_color_bgr: Annotated[list[int], FieldMeta(
        "Contour Color BGR", info="Цвет контуров в формате BGR",
    )] = [0, 255, 0]
    contour_thickness: Annotated[int, FieldMeta(
        "Contour Thickness", info="Толщина линий контуров (px)",
        min=1, max=20,
    )] = 2
