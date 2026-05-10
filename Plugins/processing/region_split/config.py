"""Конфиг RegionSplitPlugin — регионы и маршрутизация."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import PluginConfig


@register_schema("RegionSplitPluginConfigV2")
class RegionSplitPluginConfig(PluginConfig):
    """Конфиг плагина нарезки на регионы.

    Каждый регион определяется координатами и target-процессом.
    default_region — полный кадр без обрезки.
    """

    plugin_class: str = (
        "Plugins.processing.region_split.plugin.RegionSplitPlugin"
    )

    camera_id: int = 0
    resolution_width: int = 640
    resolution_height: int = 480

    # Список регионов: [{name, x, y, width, height, target}, ...]
    regions: list[dict[str, Any]] = []

    # Дефолтный регион (полный кадр)
    default_region: dict[str, str] | None = None
