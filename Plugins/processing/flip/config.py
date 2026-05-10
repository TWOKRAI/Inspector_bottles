"""Конфиг FlipPlugin — парам��тры переворота."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("FlipPluginConfigV2")
class FlipPluginConfig(PluginConfig):
    """Конфиг плагина переворота.

    Слушает region_ready, делает cv2.flip(frame, 0), отправляет region_processed.
    """

    plugin_class: str = (
        "Plugins.processing.flip.plugin.FlipPlugin"
    )

    camera_id: int = 0
    resolution_width: int = 640
    resolution_height: int = 480

    # Куда отправлять обработанный регион
    target: str = "stitcher"
