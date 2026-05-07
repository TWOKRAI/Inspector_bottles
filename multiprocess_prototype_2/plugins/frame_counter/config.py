"""Конфиг FrameCounterPlugin."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("FrameCounterPluginConfigV1")
class FrameCounterPluginConfig(PluginConfig):
    """Конфиг плагина-счётчика кадров.

    Принимает frame_ready, считает и логирует FPS.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.frame_counter.plugin.FrameCounterPlugin"
    )

    log_interval_sec: Annotated[
        float,
        FieldMeta(description="Интервал логирования FPS (секунды)"),
    ] = 5.0
