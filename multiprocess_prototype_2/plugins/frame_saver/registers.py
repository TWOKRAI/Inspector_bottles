"""FrameSaverRegisters — все параметры frame_saver плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase


@register_schema("FrameSaverRegistersV1")
class FrameSaverRegisters(SchemaBase):
    """Все параметры frame_saver — директория, формат, интервал."""

    output_dir: Annotated[str, FieldMeta(
        "Output Dir", info="Директория для сохранённых кадров",
    )] = "data/frames"

    save_every_n: Annotated[int, FieldMeta(
        "Save Every N", info="Сохранять каждый N-й кадр",
        min=1,
    )] = 10

    image_format: Annotated[str, FieldMeta(
        "Image Format", info="Формат сохранения (png/jpeg)",
    )] = "jpeg"

    jpeg_quality: Annotated[int, FieldMeta(
        "JPEG Quality", info="Качество JPEG (1-100)",
        min=1, max=100,
    )] = 85
