"""ImageAdjustRegisters — коррекция кадра (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("ImageAdjustRegistersV1")
class ImageAdjustRegisters(SchemaBase):
    """Яркость / контраст / насыщенность / гамма."""

    brightness: Annotated[float, FieldMeta("Яркость", info="Смещение яркости (-255..255)", min=-255.0, max=255.0)] = 0.0
    contrast: Annotated[
        float, FieldMeta("Контраст", info="Множитель контраста (1.0 = без изменений)", min=0.1, max=4.0)
    ] = 1.0
    saturation: Annotated[
        float, FieldMeta("Насыщенность", info="Множитель насыщенности (1.0 = без изменений)", min=0.0, max=4.0)
    ] = 1.0
    gamma: Annotated[
        float, FieldMeta("Гамма", info="Гамма-коррекция (1.0 = без изменений; >1 светлее тени)", min=0.1, max=4.0)
    ] = 1.0
