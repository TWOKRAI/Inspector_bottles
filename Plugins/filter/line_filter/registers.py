"""LineFilterRegisters — параметры фильтра виртуальной линии + FieldMeta.

Инвариант hysteresis_margin ≥ dedup_radius валидируется правилом-данными
``le_field`` у ``dedup_radius`` (ADR-DS-010) — иначе дребезг на границе зоны не
гасится. Все параметры — через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase

LineMode = Literal["enter_zone", "cross_line", "zone_edge"]


@register_schema("LineFilterRegistersV1")
class LineFilterRegisters(SchemaBase):
    """Параметры фильтра виртуальной линии."""

    # Геометрия линии
    center_x: Annotated[
        int,
        FieldMeta(
            "Center X",
            info="X-координата центра линии (px)",
            min=0,
            max=10000,
            unit="px",
        ),
    ] = 320
    center_y: Annotated[
        int,
        FieldMeta(
            "Center Y",
            info="Y-координата центра линии (px)",
            min=0,
            max=10000,
            unit="px",
        ),
    ] = 240
    angle: Annotated[
        float,
        FieldMeta(
            "Angle",
            info="Угол поворота линии (градусы)",
            min=-180,
            max=180,
            unit="°",
        ),
    ] = 0.0
    zone_width: Annotated[
        int,
        FieldMeta(
            "Zone Width",
            info="Ширина полосы вокруг линии (пунктир ±w/2)",
            min=1,
            max=500,
            unit="px",
        ),
    ] = 50

    # Логика срабатывания
    mode: Annotated[
        LineMode,
        FieldMeta(
            "Mode",
            info=(
                "enter_zone/cross_line — по трекеру (нужен match_distance ≥ смещения за кадр); "
                "zone_edge — rising-edge по занятости зоны: одно событие на проход диска, без "
                "сопоставления центров между соседними кадрами (один объект в зоне; условие: "
                "zone_width ≥ смещения за кадр); помнит место последней пропажи в зоне, чтобы "
                "потерю детекции не принять за новый диск"
            ),
        ),
    ] = "enter_zone"

    # Защита от шума
    dedup_radius: Annotated[
        int,
        FieldMeta(
            "Dedup Radius",
            info="Точки в этом радиусе считаются одним объектом (px)",
            min=1,
            max=100,
            unit="px",
            # hysteresis_margin ≥ dedup_radius — иначе дребезг границы не гасится.
            # Правило ДАННЫМИ (не model_validator): копия регистра в GUI исполняет его так же.
            rules={"le_field": "hysteresis_margin"},
        ),
    ] = 5
    min_hits: Annotated[
        int,
        FieldMeta(
            "Min Hits",
            info="Кадров подтверждения трека до зачёта (анти-вспышка)",
            min=1,
            max=30,
        ),
    ] = 2
    max_age: Annotated[
        int,
        FieldMeta(
            "Max Age",
            info=(
                "Кадров без совпадения до удаления трека. В zone_edge — окно памяти: сколько пустых "
                "кадров повторное появление ещё считается тем же объектом. "
                "Условия настройки (v — смещение за кадр, L — потеря детекции в кадрах): память работает, "
                "только если max_age ≥ rearm_frames; потеря L кадров — тот же объект при L ≤ max_age и "
                "v × (L + 1) ≤ max_match_distance (потерю короче rearm_frames держит одна защёлка); "
                "max_age × v < zone_width − max_match_distance"
            ),
            min=1,
            max=300,
        ),
    ] = 30
    max_match_distance: Annotated[
        int,
        FieldMeta(
            "Match Distance",
            info=(
                "Радиус ассоциации точки к треку (px). В zone_edge — радиус, в котором повторное "
                "появление после пустых кадров считается тем же объектом. "
                "Условие настройки (v — смещение за кадр, L — потеря детекции в кадрах): "
                "потеря L кадров — тот же объект при v × (L + 1) ≤ max_match_distance и L ≤ max_age"
            ),
            min=1,
            max=200,
            unit="px",
        ),
    ] = 20
    rearm_frames: Annotated[
        int,
        FieldMeta(
            "Re-arm Frames",
            info=(
                "zone_edge: кадров пустой зоны до пере-взвода триггера (гасит мерцание детекции). "
                "При старте плагина защёлка закрыта: занятая зона не засчитывается, "
                "триггер взводится после этого числа пустых кадров подряд. "
                "Условие настройки: память места пропажи работает, только если max_age ≥ rearm_frames "
                "(потерю короче rearm_frames держит одна защёлка)"
            ),
            min=1,
            max=60,
        ),
    ] = 2
    hysteresis_margin: Annotated[
        int,
        FieldMeta(
            "Hysteresis",
            info="Запас выхода из зоны для повторного зачёта (≥ Dedup Radius)",
            min=1,
            max=100,
            unit="px",
        ),
    ] = 6

    # Выдача
    emit_mode: Annotated[
        Literal["current", "accumulated"],
        FieldMeta(
            "Emit Mode",
            info="current — события этого кадра; accumulated — весь накопленный список",
        ),
    ] = "current"
