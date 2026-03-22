# -*- coding: utf-8 -*-
"""
Пример схемы **регистра приложения** для полей типа bool (CheckboxControl).

Копируйте и адаптируйте в пакете приложения.
"""
from typing import Annotated, ClassVar

from data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

CHECKBOX_EXAMPLE_ROUTING = FieldRouting(channel="control_example")


class CheckboxRegisterExample(SchemaBase):
    """
    Учебный регистр с одним булевым полем.

    Использование::

        from frontend_module.components.controls.checkbox.schema import CheckboxRegisterExample
    """

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    default_checkbox_value: Annotated[
        bool,
        FieldMeta(
            "Default checkbox value",
            info="Default value for checkbox.",
            routing=CHECKBOX_EXAMPLE_ROUTING,
        ),
    ] = True
