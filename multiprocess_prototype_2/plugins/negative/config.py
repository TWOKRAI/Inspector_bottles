"""Конфиг NegativePlugin — параметры инверсии."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("NegativePluginConfigV2")
class NegativePluginConfig(PluginConfig):
    """Конфиг плагина инверсии цвета.

    Слушает region_ready, делает 255 - frame, отправляет region_processed.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.negative.plugin.NegativePlugin"
    )

    camera_id: int = 0
    resolution_width: int = 640
    resolution_height: int = 480

    # Куда отправлять обработанный регион
    target: str = "stitcher"
