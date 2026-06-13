"""MaskToFrameRegisters — параметры моста маска→кадр."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("MaskToFrameRegistersV1")
class MaskToFrameRegisters(SchemaBase):
    """Какой ключ item взять как маску и положить в frame (для дисплея)."""

    source_key: Annotated[
        str,
        FieldMeta("Source Key", info="Ключ item с одноканальной маской (напр. 'mask')"),
    ] = "mask"
