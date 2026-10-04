"""RobotControlRegisters — все параметры robot_control плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


@register_schema("RobotControlRegistersV1")
class RobotControlRegisters(SchemaBase):
    """Все параметры robot_control — управление отбраковкой."""

    # Флаг включения отбраковки
    enabled: Annotated[
        bool,
        FieldMeta(
            "Enabled",
            info="Включена ли отбраковка",
        ),
    ] = True

    # Минимальная площадь дефекта для reject
    min_defect_area: Annotated[
        int,
        FieldMeta(
            "Min Defect Area",
            info="Минимальная площадь дефекта для reject (пикселей)",
            min=0,
            unit="px²",
        ),
    ] = 500

    # Task 5.2: время пути изделия от камеры до толкателя. Цель привода —
    # capture_ts + transit_ms; 0 — привод срабатывает сразу на решении.
    transit_ms: Annotated[
        int,
        FieldMeta(
            "Transit",
            info="Время пути изделия от кадра до толкателя (0 — срабатывание сразу на решении)",
            unit="ms",
            min=0,
        ),
    ] = 0

    # Task 5.2: допуск окна привода. Цель, чьё окно закрылось раньше чем
    # tolerance назад, не стреляет (missed); выстрел позже fire_at + tolerance
    # считается опозданием (late_fires).
    actuation_tolerance_ms: Annotated[
        int,
        FieldMeta(
            "Actuation Tolerance",
            info="Допуск окна привода: позже — missed / late_fires",
            unit="ms",
            min=0,
        ),
    ] = 20

    # Устарело (Task 5.2): прежний сон в process(). Алиас transit_ms —
    # действует, только если transit_ms == 0; при ненулевом значении WARNING.
    reject_delay_ms: Annotated[
        int,
        FieldMeta(
            "Reject Delay (deprecated)",
            info="Устарело: алиас transit_ms (действует при transit_ms = 0)",
            unit="ms",
            min=0,
        ),
    ] = 0

    # Реакция на маркер not_inspected (Task 4.7d-4): кадр не проверен, а не «годен»
    not_inspected_action: Annotated[
        Literal["reject", "pass"],
        FieldMeta(
            "Not Inspected Action",
            info="Реакция на маркер not_inspected (кадр не проверен): reject — отбраковать, pass — пропустить",
        ),
    ] = "reject"

    # Максимум детекций для reject (0 = любое количество)
    max_detections_for_reject: Annotated[
        int,
        FieldMeta(
            "Max Detections For Reject",
            info="Максимум детекций для reject (0 = любое количество)",
            min=0,
        ),
    ] = 0
