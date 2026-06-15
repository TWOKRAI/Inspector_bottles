"""ControlPanelRegisters — runtime-tunable параметры пульта."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import register_schema


@register_schema("ControlPanelRegistersV1")
class ControlPanelRegisters(SchemaBase):
    """Tunable-параметры пульта (live-правка из инспектора)."""

    hold_last: Annotated[
        bool,
        FieldMeta(
            "Держать значения",
            info="Зарезервировано: пульт держит значения контролов между эмитами.",
            widget="checkbox",
        ),
    ] = True
