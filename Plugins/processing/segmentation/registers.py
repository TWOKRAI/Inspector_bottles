"""SegmentationRegisters — параметры удаления фона (live-tunable)."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("SegmentationRegistersV1")
class SegmentationRegisters(SchemaBase):
    """Параметры сегментации человека (фон → белый)."""

    threshold: Annotated[
        float,
        FieldMeta("Порог маски", info="Порог уверенности маски человека (0..1)", min=0.0, max=1.0),
    ] = 0.5
    bg_white: Annotated[
        bool,
        FieldMeta("Белый фон", info="True = фон белый; False = фон чёрный"),
    ] = True
    model_path: Annotated[
        str,
        FieldMeta("Путь к модели", info="Пусто = авто-поиск selfie_segmenter.tflite в кэше"),
    ] = ""
