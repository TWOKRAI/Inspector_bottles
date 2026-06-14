"""ContourFinderRegisters — фильтр контуров по площади (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("ContourFinderRegistersV1")
class ContourFinderRegisters(SchemaBase):
    """Параметры поиска контуров на бинарной маске."""

    min_area: Annotated[int, FieldMeta("Min Area", info="Мин. площадь контура (px²)", min=0, unit="px²")] = 100
    max_area: Annotated[int, FieldMeta("Max Area", info="Макс. площадь (0 = без ограничения)", min=0, unit="px²")] = 0
    keep_mask: Annotated[
        bool,
        FieldMeta("Keep Mask", info="Не дропать маску после поиска (нужно display-ветке для показа маски)"),
    ] = False
