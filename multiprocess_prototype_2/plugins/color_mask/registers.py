"""ColorMaskRegisters — все параметры color_mask плагина.

V3_MY_PURE: register = единый источник параметров + memory + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase


@register_schema("ColorMaskRegistersV3")
class ColorMaskRegisters(SchemaBase):
    """Все параметры color_mask — startup + runtime.

    Используется как:
      - managed register (через RegistersManager → GUI видит и меняет)
      - локальный объект параметров внутри плагина (без RegistersManager)

    Hue: 0..179 (OpenCV HSV convention).
    Saturation, Value: 0..255.
    """

    # Параметры камеры / SHM
    camera_id: Annotated[int, FieldMeta("ID камеры", info="Для SHM-имён")] = 0
    resolution_width: Annotated[int, FieldMeta("Ширина кадра", unit="px")] = 640
    resolution_height: Annotated[int, FieldMeta("Высота кадра", unit="px")] = 480

    # HSV-пороги (runtime-tunable — GUI слайдеры)
    h_min: Annotated[int, FieldMeta(
        "Min Hue", info="Нижняя граница H в HSV (0..179 OpenCV)",
        min=0, max=179, unit="°",
    )] = 0
    h_max: Annotated[int, FieldMeta(
        "Max Hue", info="Верхняя граница H в HSV (0..179 OpenCV)",
        min=0, max=179, unit="°",
    )] = 179
    s_min: Annotated[int, FieldMeta(
        "Min Saturation", info="Нижняя граница S", min=0, max=255,
    )] = 50
    s_max: Annotated[int, FieldMeta(
        "Max Saturation", info="Верхняя граница S", min=0, max=255,
    )] = 255
    v_min: Annotated[int, FieldMeta(
        "Min Value", info="Нижняя граница V", min=0, max=255,
    )] = 50
    v_max: Annotated[int, FieldMeta(
        "Max Value", info="Верхняя граница V", min=0, max=255,
    )] = 255

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout для выходной маски (1 канал)."""
        return {
            f"mask_{self.camera_id}": (self.resolution_height, self.resolution_width, 1),
            "coll": 1,
        }
