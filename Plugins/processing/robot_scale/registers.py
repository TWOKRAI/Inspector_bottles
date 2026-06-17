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

    # Углы листа A4 в реальных координатах робота (мм) — задаются ОДИН РАЗ (где лист на столе).
    x0: Annotated[float, FieldMeta("Угол ЛВ X (мм)", info="левый-верхний X на столе", min=-2000.0, max=2000.0)] = 0.0
    y0: Annotated[float, FieldMeta("Угол ЛВ Y (мм)", info="левый-верхний Y на столе", min=-2000.0, max=2000.0)] = 0.0
    x1: Annotated[float, FieldMeta("Угол ПН X (мм)", info="правый-нижний X на столе", min=-2000.0, max=2000.0)] = 200.0
    y1: Annotated[
        float,
        FieldMeta("Угол ПН Y (мм)", info="правый-нижний Y (для Y-вверх: y0 > y1)", min=-2000.0, max=2000.0),
    ] = 200.0

    # Лист повёрнут 90° в системе координат робота (как физически лежит на столе):
    # робот-X идёт по ВЕРТИКАЛИ кадра (py), робот-Y — по ГОРИЗОНТАЛИ (px). На экране
    # портрет остаётся ровным (points_render так же swap-ит обратно), меняются только
    # координаты для робота. False — оси совпадают (робот-X из px, робот-Y из py).
    swap_axes: Annotated[
        bool, FieldMeta("Повернуть оси (лист 90°)", info="робот-X из вертикали кадра, робот-Y из горизонтали")
    ] = False

    # Сохранять пропорции рисунка (единый масштаб по X/Y + центрирование в зоне).
    # True — портрет не сжимается, даже если зона не совпадает с аспектом кадра
    # (вписывается по меньшей стороне, центрируется). False — растягивать на всю зону.
    keep_aspect: Annotated[
        bool, FieldMeta("Сохранять пропорции", info="единый масштаб X/Y + центрирование (без искажения)")
    ] = True

    # Размещение рисунка ВНУТРИ листа (правится вживую): масштаб + сдвиг (мм).
    # draw_scale=1 + offset=0 → рисунок заполняет лист (как раньше). Лист (draw_bounds)
    # не меняется — рисунок ездит/масштабируется внутри него.
    draw_scale: Annotated[
        float,
        FieldMeta("Масштаб рисунка", info="доля листа (1=на весь лист, 0.5=половина)", min=0.01, max=10.0),
    ] = 1.0
    offset_x: Annotated[
        float, FieldMeta("Сдвиг рисунка X (мм)", info="смещение по столу вправо", min=-2000.0, max=2000.0)
    ] = 0.0
    offset_y: Annotated[
        float, FieldMeta("Сдвиг рисунка Y (мм)", info="смещение по столу вверх/вниз", min=-2000.0, max=2000.0)
    ] = 0.0

    # Прижим к рабочей зоне (листу): точка за прямоугольником листа кладётся на его
    # границу (а не вылетает за лист). Защита от draw_scale/offset/поворота за пределы
    # листа; firmware clampW — лишь предел s16, не зона. Точка «ставится на краю».
    # Дефолт False (без изменения старого поведения); рецепт рисования включает.
    clamp_to_zone: Annotated[
        bool, FieldMeta("Прижать к листу", info="точка за листом ложится на его границу (не вылетает)")
    ] = False

    # Счётчики (readonly).
    points_last: Annotated[int, FieldMeta("Точек смасштабировано", readonly=True)] = 0
    points_clamped: Annotated[int, FieldMeta("Точек прижато к краю", readonly=True)] = 0
