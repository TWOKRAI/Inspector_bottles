"""OverlayDrawRegisters — таблица цветов по type+group + дефолты стиля.

color_table (list[dict]) редактируется generic JSON-редактором инспектора. Резолв
стиля фигуры: per-shape явный color → строка по group → строка по type → дефолт.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("OverlayDrawRegistersV1")
class OverlayDrawRegisters(SchemaBase):
    """Параметры рисовальщика overlay."""

    # Таблица цветов: строки {type|group → color/thickness/...}.
    color_table: Annotated[
        list[dict],
        FieldMeta(
            "Color Table",
            info='Цвет/толщина по type или group, напр. [{"type":"line","color":[0,255,255],"thickness":2}]',
        ),
    ] = [
        {"type": "line", "color": [0, 255, 0], "thickness": 4},
        {"type": "dashed", "color": [0, 255, 0], "thickness": 3},
        {"type": "point", "color": [255, 0, 255], "radius": 8},
    ]

    # Дефолты (фолбэк, если фигура/таблица не задали стиль).
    default_line_color: Annotated[
        list[int],
        FieldMeta(
            "Default Line Color BGR",
            info="Цвет линий по умолчанию (BGR)",
        ),
    ] = [0, 255, 255]
    default_point_color: Annotated[
        list[int],
        FieldMeta(
            "Default Point Color BGR",
            info="Цвет точек по умолчанию (BGR)",
        ),
    ] = [0, 0, 255]
    default_thickness: Annotated[
        int,
        FieldMeta(
            "Default Thickness",
            info="Толщина линий по умолчанию (px)",
            min=1,
            max=20,
        ),
    ] = 2
    default_point_radius: Annotated[
        int,
        FieldMeta(
            "Default Point Radius",
            info="Радиус точек по умолчанию (px)",
            min=1,
            max=50,
        ),
    ] = 5
    dash_len: Annotated[
        int,
        FieldMeta(
            "Dash Length",
            info="Длина штриха пунктира (px)",
            min=2,
            max=50,
            unit="px",
        ),
    ] = 8
    gap_len: Annotated[
        int,
        FieldMeta(
            "Gap Length",
            info="Длина разрыва пунктира (px)",
            min=2,
            max=50,
            unit="px",
        ),
    ] = 6
    show_labels: Annotated[
        bool,
        FieldMeta(
            "Show Labels",
            info="Рисовать подписи точек (label)",
        ),
    ] = True
