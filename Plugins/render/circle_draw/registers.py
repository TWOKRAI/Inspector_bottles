"""CircleDrawRegisters — параметры отрисовки окружностей из detections."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("CircleDrawRegistersV1")
class CircleDrawRegisters(SchemaBase):
    """Цвет/толщина окружностей, отметка центра. Рисует item['detections'] на кадре."""

    color_bgr: Annotated[
        list[int],
        FieldMeta("Circle Color BGR", info="Цвет окружностей (BGR)", widget="color3"),
    ] = [0, 255, 0]
    thickness: Annotated[
        int,
        FieldMeta("Thickness", info="Толщина линии окружности (px)", min=1, max=20),
    ] = 2
    draw_center: Annotated[
        bool,
        FieldMeta("Draw Center", info="Отмечать центр окружности точкой"),
    ] = True
    show_radius: Annotated[
        bool,
        FieldMeta("Show Radius", info="Подписать радиус (px) рядом с окружностью"),
    ] = False
