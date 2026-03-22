# -*- coding: utf-8 -*-
"""
Пример схемы **регистра приложения** для полей, редактируемых SliderControl.

Копируйте и адаптируйте в пакете приложения (``registers/schemas/...``).
Поля для слайдера: int/float с ``FieldMeta(min, max, unit, transfer_k, round_k)``.
"""
from typing import Annotated, ClassVar

from data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

SLIDER_EXAMPLE_ROUTING = FieldRouting(channel="control_example")


class SliderRegisterExample(SchemaBase):
    """
    Учебный регистр с одним числовым полем под слайдер.

    Использование в приложении::

        from frontend_module.components.controls.slider.schema import SliderRegisterExample
    """

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    default_slider_value: Annotated[
        int,
        FieldMeta(
            "Default slider value",
            info="Default value for slider.",
            routing=SLIDER_EXAMPLE_ROUTING,
        ),
    ] = 500
