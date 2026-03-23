# -*- coding: utf-8 -*-
"""
Регистр с тройкой float (BGR) + UI для ``CompoundNumericControl`` (три слайдера/спинбокса по индексу).
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

EXAMPLE_BGR_ROUTING = FieldRouting(channel="control_example")


@register_schema("ExampleBgrTripletRegister")
class ExampleBgrTripletRegister(SchemaBase):
    """
    Три канала в одном поле; ``CompoundNumericControl`` создаёт ``BindingConfig`` с ``index`` 0,1,2.
    """

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_bgr"
    BINDING_FIELD: ClassVar[str] = "bgr_triplet"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    bgr_triplet: Annotated[
        tuple[float, float, float],
        FieldMeta(
            "BGR",
            info="Три компонента; индексы 0,1,2 в UI.",
            routing=EXAMPLE_BGR_ROUTING,
            min=0.0,
            max=255.0,
            transfer_k=1.0,
            round_k=0,
        ),
    ] = (128.0, 128.0, 128.0)


@register_schema("ExampleCompoundNumericUiConfig")
class ExampleCompoundNumericUiConfig(SchemaBase):
    """UI для трёх каналов и типа числового контрола."""

    label_b: Annotated[str, FieldMeta("Подпись канала B")] = "B"
    label_g: Annotated[str, FieldMeta("Подпись канала G")] = "G"
    label_r: Annotated[str, FieldMeta("Подпись канала R")] = "R"

    numeric_view_type: Annotated[
        Literal["slider", "spinbox"],
        FieldMeta("Тип контрола"),
    ] = "slider"

    show_ticks: Annotated[
        bool,
        FieldMeta("Деления (только слайдер)"),
    ] = False

    label_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"

    channel_widget_enabled: Annotated[
        bool,
        FieldMeta("Каналы доступны"),
    ] = True

    channel_min: Annotated[
        float | None,
        FieldMeta("Мин. (переопределение)", info="None — из FieldMeta регистра."),
    ] = None

    channel_max: Annotated[
        float | None,
        FieldMeta("Макс. (переопределение)", info="None — из FieldMeta регистра."),
    ] = None
