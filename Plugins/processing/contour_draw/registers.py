"""ContourDrawRegisters — цвет и толщина линии контура (live-tunable слайдеры)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("ContourDrawRegistersV1")
class ContourDrawRegisters(SchemaBase):
    """Параметры отрисовки контура (BGR-компоненты + толщина)."""

    color_b: Annotated[int, FieldMeta("Синий (B)", info="Компонента B цвета линии", min=0, max=255)] = 0
    color_g: Annotated[int, FieldMeta("Зелёный (G)", info="Компонента G цвета линии", min=0, max=255)] = 255
    color_r: Annotated[int, FieldMeta("Красный (R)", info="Компонента R цвета линии", min=0, max=255)] = 0
    thickness: Annotated[int, FieldMeta("Толщина", info="Толщина линии (px)", min=1, max=20, unit="px")] = 2
