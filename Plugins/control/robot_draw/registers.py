"""RobotDrawRegisters — параметры и телеметрия плагина robot_draw."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("RobotDrawRegistersV1")
class RobotDrawRegisters(SchemaBase):
    """Параметры рисования (перо/скорость) + прогресс исполнения."""

    # --- Перо и траектория ---
    pen_down_mm: Annotated[float, FieldMeta("Перо опущено (Z)", unit="mm", min=-500.0, max=500.0)] = 0.0
    pen_up_mm: Annotated[float, FieldMeta("Перо поднято (Z)", unit="mm", min=-500.0, max=500.0)] = 10.0
    lift_mm: Annotated[
        float, FieldMeta("Подъём над Z фигуры", info="Высота переезда", unit="mm", min=1.0, max=100.0)
    ] = 10.0
    draw_speed_pct: Annotated[int, FieldMeta("Скорость рисования", unit="%", min=1, max=100)] = 30
    overlap_mm: Annotated[float, FieldMeta("Скругление углов (PASS)", unit="mm", min=0.1, max=50.0)] = 1.0
    draw_timeout_s: Annotated[float, FieldMeta("Таймаут прохода", unit="s", min=5.0, max=600.0)] = 120.0

    # --- Поведение в pipeline ---
    points_source: Annotated[str, FieldMeta("Ключ точек в item", info="list[{x_mm,y_mm,pen}] -> очередь рисования")] = (
        "points"
    )
    auto_draw: Annotated[
        bool, FieldMeta("Авто-рисование из item", info="ОСТОРОЖНО: рисует всё, что пришло по points_source")
    ] = False

    # --- Телеметрия (readonly) ---
    state: Annotated[str, FieldMeta("Состояние", info="idle | drawing | done | failed", readonly=True)] = "idle"
    busy: Annotated[bool, FieldMeta("Робот рисует", readonly=True)] = False
    progress_point: Annotated[int, FieldMeta("Текущая точка", readonly=True)] = 0
    total_points: Annotated[int, FieldMeta("Точек в задании", readonly=True)] = 0
    draws_done: Annotated[int, FieldMeta("Фигур нарисовано", readonly=True)] = 0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
