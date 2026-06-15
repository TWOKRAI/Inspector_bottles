"""PointsRenderRegisters — параметры карты точек (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("PointsRenderRegistersV1")
class PointsRenderRegisters(SchemaBase):
    """Параметры визуализации карты точек робота."""

    points_source: Annotated[str, FieldMeta("Ключ точек в item", info="list[{x_mm,y_mm,pen}] для рендера")] = (
        "draw_points"
    )
    canvas_width: Annotated[int, FieldMeta("Ширина холста", min=64, max=4096, unit="px")] = 640
    canvas_height: Annotated[int, FieldMeta("Высота холста", min=64, max=4096, unit="px")] = 480
    bg_white: Annotated[bool, FieldMeta("Белый фон", info="True = белый, False = чёрный")] = True
    dot_radius: Annotated[int, FieldMeta("Радиус точки", info="0 = без кружков", min=0, max=10, unit="px")] = 2
    show_travel: Annotated[bool, FieldMeta("Холостые ходы", info="Красный пунктир pen-up переходов")] = True
    points_last: Annotated[int, FieldMeta("Точек на карте", readonly=True)] = 0
