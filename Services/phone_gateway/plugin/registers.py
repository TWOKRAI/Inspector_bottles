"""PhoneCameraRegisters — runtime-tunable параметры источника «телефон»."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import register_schema


@register_schema("PhoneCameraRegistersV1")
class PhoneCameraRegisters(SchemaBase):
    """Tunable-параметры источника «телефон» (live-правка из инспектора)."""

    hold_last: Annotated[
        bool,
        FieldMeta(
            "Держать последнее фото",
            info="Вкл: последний снимок показывается постоянно. "
            "Выкл: каждый снимок отдаётся в pipeline один раз (дискретно).",
            widget="checkbox",
        ),
    ] = True
