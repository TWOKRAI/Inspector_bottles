"""BlobFilterRegisters — фильтр связных областей по площади (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("BlobFilterRegistersV1")
class BlobFilterRegisters(SchemaBase):
    """Параметры очистки бинарной маски линий от шумовых blob'ов."""

    min_area: Annotated[
        int,
        FieldMeta("Min Area", info="Стереть области меньше (px)", min=0, max=50000, unit="px²"),
    ] = 10
    max_area: Annotated[
        int,
        FieldMeta("Max Area", info="Стереть области больше (0 = без ограничения)", min=0, unit="px²"),
    ] = 0
