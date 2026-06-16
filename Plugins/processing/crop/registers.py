"""CropRegisters — прямоугольник обрезки кадра (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CropRegistersV1")
class CropRegisters(SchemaBase):
    """Обрезка кадра по прямоугольнику [crop_x, crop_y, crop_w, crop_h] (пиксели).

    Вырезанный регион ресайзится к выходному размеру (по умолчанию — размер
    ИСХОДНОГО кадра), чтобы размерности тракта не «плыли» (strokes_to_points /
    robot_scale работают с постоянным src). Всё ноль → проброс без изменений.
    """

    crop_x: Annotated[int, FieldMeta("Обрезка: X (px)", info="левый край региона", min=0, max=10000)] = 0
    crop_y: Annotated[int, FieldMeta("Обрезка: Y (px)", info="верхний край региона", min=0, max=10000)] = 0
    crop_w: Annotated[int, FieldMeta("Обрезка: ширина (px)", info="0 = до правого края", min=0, max=10000)] = 0
    crop_h: Annotated[int, FieldMeta("Обрезка: высота (px)", info="0 = до нижнего края", min=0, max=10000)] = 0
    out_width: Annotated[int, FieldMeta("Выход: ширина (px)", info="0 = как исходный кадр", min=0, max=10000)] = 0
    out_height: Annotated[int, FieldMeta("Выход: высота (px)", info="0 = как исходный кадр", min=0, max=10000)] = 0

    # readonly: фактический размер вырезанного региона.
    last_w: Annotated[int, FieldMeta("Регион: ширина", readonly=True)] = 0
    last_h: Annotated[int, FieldMeta("Регион: высота", readonly=True)] = 0
