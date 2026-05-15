# -*- coding: utf-8 -*-

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
)


class CheckboxRegister(SchemaBase):
    """Пример регистра для Checkbox"""

    checkbox: Annotated[
        bool,
        FieldMeta(
            widget="checkbox",
            description="Checkbox",
            info="Пример регистра для Checkbox",
        ),
    ] = False
