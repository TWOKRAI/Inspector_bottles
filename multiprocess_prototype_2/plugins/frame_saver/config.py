"""Конфиг FrameSaverPlugin."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("FrameSaverPluginConfigV1")
class FrameSaverPluginConfig(PluginConfig):
    """Конфиг плагина сохранения кадров на диск.

    Сохраняет каждый N-й кадр в output_dir.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.frame_saver.plugin.FrameSaverPlugin"
    )
    plugin_name: str = "frame_saver"
    category: str = "output"

    output_dir: Annotated[
        str,
        FieldMeta(description="Директория для сохранённых кадров"),
    ] = "data/frames"

    save_every_n: Annotated[
        int,
        FieldMeta(description="Сохранять каждый N-й кадр"),
    ] = 10

    image_format: Annotated[
        Literal["png", "jpeg"],
        FieldMeta(description="Формат сохранения (png/jpeg)"),
    ] = "jpeg"

    jpeg_quality: Annotated[
        int,
        FieldMeta(description="Качество JPEG (1-100)"),
    ] = 85
