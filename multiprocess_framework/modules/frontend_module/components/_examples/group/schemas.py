# -*- coding: utf-8 -*-
"""
Только UI: строка «подпись + slider/spinbox» через ``create_labeled_numeric_view``.

Без регистра и ``NumericPresenter`` — чтобы показать слой ``group/`` изолированно.
"""
from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.frontend_module.schema_adapter import FieldMeta, SchemaBase, register_schema


@register_schema("ExampleGroupRowUiConfig")
class ExampleGroupRowUiConfig(SchemaBase):
    """Параметры демо-виджета ``LabeledNumericGroupView``."""

    row_label: Annotated[str, FieldMeta("Текст метки")] = "Значение"
    row_tooltip: Annotated[str, FieldMeta("Подсказка метки")] = ""

    view_type: Annotated[
        Literal["slider", "spinbox"],
        FieldMeta("Тип значения"),
    ] = "slider"

    label_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"

    show_ticks: Annotated[bool, FieldMeta("Деления слайдера")] = False

    value_min: Annotated[
        float | None,
        FieldMeta("Мин. для set_range", info="Оба min/max заданы — вызывается set_range."),
    ] = 0.0

    value_max: Annotated[
        float | None,
        FieldMeta("Макс. для set_range"),
    ] = 100.0

    step: Annotated[float, FieldMeta("Шаг")] = 1.0

    initial_value: Annotated[float, FieldMeta("Начальное значение (без эмита)")] = 42.0

    widget_enabled: Annotated[bool, FieldMeta("Доступность редактирования")] = True
