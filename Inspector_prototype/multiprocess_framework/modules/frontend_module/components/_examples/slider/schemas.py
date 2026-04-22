# -*- coding: utf-8 -*-
"""
Две SchemaBase: регистр (ExampleSliderValueRegister) и UI (ExampleSliderUiConfig).

Паттерн как в ``control_v2.examples.checkbox``: BINDING_* на классе регистра.
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

EXAMPLE_SLIDER_ROUTING = FieldRouting(channel="control_example")


@register_schema("ExampleSliderValueRegister")
class ExampleSliderValueRegister(SchemaBase):
    """
    Числовое поле регистра + FieldMeta для ResolvedMeta и маршрутизации.

    BINDING_FIELD должен совпадать с именем поля-схемы (demo_threshold).
    """

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_slider"
    BINDING_FIELD: ClassVar[str] = "demo_threshold"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    demo_threshold: Annotated[
        float,
        FieldMeta(
            "Демо-порог",
            info="Числовое значение в регистре; подпись UI из ExampleSliderUiConfig или FieldMeta.",
            routing=EXAMPLE_SLIDER_ROUTING,
            min=0.0,
            max=100.0,
            transfer_k=0.1,
            round_k=1,
        ),
    ] = 50.0


@register_schema("ExampleSliderUiConfig")
class ExampleSliderUiConfig(SchemaBase):
    """Только отображение; не участвует в register_update."""

    slider_label: Annotated[
        str,
        FieldMeta(
            "Подпись",
            info="Пустая строка: адаптер не переопределяет label (берётся из FieldMeta регистра).",
        ),
    ] = ""

    slider_tooltip: Annotated[
        str,
        FieldMeta("Подсказка", info="Tooltip метки; пусто — описание из регистра."),
    ] = ""

    slider_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"

    slider_show_ticks: Annotated[
        bool,
        FieldMeta("Показать деления"),
    ] = False

    slider_min: Annotated[
        float | None,
        FieldMeta("Мин. значение", info="None — из метаданных регистра."),
    ] = None

    slider_max: Annotated[
        float | None,
        FieldMeta("Макс. значение", info="None — из метаданных регистра."),
    ] = None

    slider_widget_enabled: Annotated[
        bool,
        FieldMeta("Виджет доступен"),
    ] = True
