# -*- coding: utf-8 -*-
"""
Демо для фасада ``NumericControl`` (единая точка входа: slider или spinbox по ``view_type``).

Отдельно от ``examples/slider`` и ``examples/spinbox``: те вызывают специализированные фасады.
"""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

EXAMPLE_NUMERIC_ROUTING = FieldRouting(channel="control_example")


@register_schema("ExampleNumericValueRegister")
class ExampleNumericValueRegister(SchemaBase):
    """Одно float-поле; привязка к ``NumericControl``."""

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_numeric"
    BINDING_FIELD: ClassVar[str] = "demo_scalar"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    demo_scalar: Annotated[
        float,
        FieldMeta(
            "Скаляр (numeric)",
            info="Демо для NumericControl; подпись из UI-схемы или FieldMeta.",
            routing=EXAMPLE_NUMERIC_ROUTING,
            min=0.0,
            max=100.0,
            transfer_k=0.1,
            round_k=1,
        ),
    ] = 33.0


@register_schema("ExampleNumericUiConfig")
class ExampleNumericUiConfig(SchemaBase):
    """Только отображение; не участвует в register_update."""

    numeric_label: Annotated[
        str,
        FieldMeta(
            "Подпись",
            info="Пустая строка: label из метаданных регистра.",
        ),
    ] = ""

    numeric_tooltip: Annotated[
        str,
        FieldMeta("Подсказка"),
    ] = ""

    numeric_view_type: Annotated[
        Literal["slider", "spinbox"],
        FieldMeta("Тип числового виджета"),
    ] = "slider"

    numeric_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"

    numeric_show_ticks: Annotated[
        bool,
        FieldMeta("Деления (только slider)"),
    ] = False

    numeric_min: Annotated[
        float | None,
        FieldMeta("Мин.", info="None — из метаданных."),
    ] = None

    numeric_max: Annotated[
        float | None,
        FieldMeta("Макс.", info="None — из метаданных."),
    ] = None

    numeric_widget_enabled: Annotated[
        bool,
        FieldMeta("Виджет доступен"),
    ] = True
