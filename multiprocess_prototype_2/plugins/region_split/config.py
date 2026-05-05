"""Конфиг RegionSplitPlugin — регионы и маршрутизация."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("RegionSplitPluginConfigV2")
class RegionSplitPluginConfig(PluginConfig):
    """Конфиг плагина нарезки на регионы.

    Каждый регион определяется координатами и target-процессом.
    default_region — полный кадр без обрезки.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.region_split.plugin.RegionSplitPlugin"
    )
    plugin_name: str = "region_split"
    category: str = "processing"

    camera_id: int = 0
    resolution_width: int = 640
    resolution_height: int = 480

    # Список регионов: [{name, x, y, width, height, target}, ...]
    regions: list[dict[str, Any]] = []

    # Дефолтный регион (полный кадр)
    default_region: dict[str, str] | None = None

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM-слоты: один на каждый регион + default."""
        mem: dict[str, Any] = {}
        for r in self.regions:
            name = r.get("name", "region")
            w = int(r.get("width", self.resolution_width))
            h = int(r.get("height", self.resolution_height))
            mem[f"{name}_{self.camera_id}"] = (h, w, 3)

        if self.default_region:
            name = self.default_region.get("name", "region_default")
            mem[f"{name}_{self.camera_id}"] = (self.resolution_height, self.resolution_width, 3)

        mem["coll"] = 1
        return mem
