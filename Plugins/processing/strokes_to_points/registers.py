"""StrokesToPointsRegisters — параметры конвертера линия→точки (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("StrokesToPointsRegistersV1")
class StrokesToPointsRegisters(SchemaBase):
    """Параметры извлечения пути робота из бинарной маски линий."""

    # --- Центральная линия vs контур ---
    centerline: Annotated[
        bool,
        FieldMeta("Центральная линия", info="True = скелет (одна линия); False = контур (две линии)"),
    ] = True

    # --- Прореживание точек ---
    reduce_mode: Annotated[
        str,
        FieldMeta("Режим прореживания", info="dp | step | angle | none"),
    ] = "dp"
    simplify_epsilon: Annotated[
        float,
        FieldMeta("DP epsilon", info="Douglas-Peucker: чем больше, тем меньше точек", min=0.0, max=20.0),
    ] = 1.0
    step_px: Annotated[
        float,
        FieldMeta("Шаг (px)", info="Равномерный шаг ресемплинга по длине линии", min=0.5, max=200.0),
    ] = 5.0
    angle_threshold_deg: Annotated[
        float,
        FieldMeta("Порог угла (°)", info="Точка ставится, где поворот линии больше угла", min=0.0, max=180.0),
    ] = 15.0

    # --- Фильтр коротких/длинных штрихов (в пикселях) ---
    min_stroke_len: Annotated[
        float,
        FieldMeta("Min длина штриха (px)", info="Отбросить штрихи короче", min=0.0, max=2000.0),
    ] = 10.0
    max_stroke_len: Annotated[
        float,
        FieldMeta("Max длина штриха (px)", info="Отбросить штрихи длиннее (0 = off)", min=0.0),
    ] = 0.0

    # --- Рабочая зона по углам (приоритетный режим, если включён) ---
    zone_mode: Annotated[
        bool,
        FieldMeta("Зона по углам", info="True = вписать кадр в прямоугольник робота (углы ниже)"),
    ] = False
    zone_x0: Annotated[float, FieldMeta("Зона X0 ЛВ (мм)", info="Левый-верхний угол X", min=-2000.0, max=2000.0)] = 0.0
    zone_y0: Annotated[float, FieldMeta("Зона Y0 ЛВ (мм)", info="Левый-верхний угол Y", min=-2000.0, max=2000.0)] = 0.0
    zone_x1: Annotated[
        float,
        FieldMeta("Зона X1 ПН (мм)", info="Правый-нижний угол X", min=-2000.0, max=2000.0),
    ] = 100.0
    zone_y1: Annotated[
        float,
        FieldMeta("Зона Y1 ПН (мм)", info="Правый-нижний угол Y (для Y-вверх: y0>y1)", min=-2000.0, max=2000.0),
    ] = 100.0

    # --- Перевод пиксели → мм (scale + offset, как trajectory.py; если zone_mode=False) ---
    scale_x: Annotated[float, FieldMeta("Scale X (мм/px)", info="мм на пиксель по X", min=0.001, max=10.0)] = 0.1
    scale_y: Annotated[float, FieldMeta("Scale Y (мм/px)", info="мм на пиксель по Y", min=0.001, max=10.0)] = 0.1
    offset_x: Annotated[float, FieldMeta("Offset X (мм)", info="Смещение начала по X", min=-2000.0, max=2000.0)] = 0.0
    offset_y: Annotated[float, FieldMeta("Offset Y (мм)", info="Смещение начала по Y", min=-2000.0, max=2000.0)] = 0.0
    flip_y: Annotated[
        bool,
        FieldMeta("Инвертировать Y", info="Экранный Y вниз → робот Y вверх (y = H - py)"),
    ] = True

    # --- Защита от гигантского пути ---
    max_points: Annotated[
        int,
        FieldMeta("Max точек", info="0 = без лимита; иначе обрезать путь по штрихам", min=0),
    ] = 0

    # --- Счётчики (readonly) ---
    points_last: Annotated[int, FieldMeta("Точек в пути", readonly=True)] = 0
    strokes_last: Annotated[int, FieldMeta("Штрихов в пути", readonly=True)] = 0
