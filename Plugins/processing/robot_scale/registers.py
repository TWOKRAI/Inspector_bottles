"""RobotScaleRegisters — масштаб точек px → реальные координаты робота (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("RobotScaleRegistersV1")
class RobotScaleRegisters(SchemaBase):
    """Вписывание пиксельного пути в прямоугольник реального листа робота.

    Точки приходят в пикселях (strokes_to_points в identity-режиме). Пиксельный
    кадр [0..src_width]×[0..src_height] линейно вписывается в прямоугольник робота
    с углами (x0,y0) левый-верхний и (x1,y1) правый-нижний (реальные мм). Ориентацию
    по Y задаёшь значениями углов (для робота Y-вверх ставь y0 > y1).
    """

    # Ключ точек в item (вход и выход — один ключ; путь перезаписывается в мм).
    points_source: Annotated[
        str,
        FieldMeta("Ключ точек в item", info="[{x_mm,y_mm,pen}] в пикселях → перезапишутся в мм"),
    ] = "draw_points"

    # Размер исходного пиксельного кадра (из чего пришли точки).
    src_width: Annotated[int, FieldMeta("Ширина кадра (px)", info="пиксельный диапазон X входа", min=1)] = 640
    src_height: Annotated[int, FieldMeta("Высота кадра (px)", info="пиксельный диапазон Y входа", min=1)] = 480

    # Углы листа в реальных координатах робота (мм).
    x0: Annotated[float, FieldMeta("Угол ЛВ X (мм)", info="левый-верхний X на столе", min=-2000.0, max=2000.0)] = 0.0
    y0: Annotated[float, FieldMeta("Угол ЛВ Y (мм)", info="левый-верхний Y на столе", min=-2000.0, max=2000.0)] = 0.0
    x1: Annotated[float, FieldMeta("Угол ПН X (мм)", info="правый-нижний X на столе", min=-2000.0, max=2000.0)] = 200.0
    y1: Annotated[
        float,
        FieldMeta("Угол ПН Y (мм)", info="правый-нижний Y (для Y-вверх: y0 > y1)", min=-2000.0, max=2000.0),
    ] = 200.0

    # Счётчик (readonly).
    points_last: Annotated[int, FieldMeta("Точек смасштабировано", readonly=True)] = 0
