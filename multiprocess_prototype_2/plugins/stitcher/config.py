"""Конфиг StitcherPlugin — параметры склейки."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("StitcherPluginConfigV2")
class StitcherPluginConfig(PluginConfig):
    """Конфиг плагина склейки регионов.

    Собирает region_processed от нескольких процессов,
    буферизует по seq_id, склеивает на canvas по координатам.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.stitcher.plugin.StitcherPlugin"
    )
    plugin_name: str = "stitcher"
    category: str = "processing"

    camera_id: int = 0
    resolution_width: int = 640
    resolution_height: int = 480

    # Имена ожидаемых регионов (для определения полноты кадра)
    expected_regions: list[str] = []

    # Layout: "original" = размещать по координатам из метаданных
    layout: str = "original"

    # Таймаут ожидания неполного кадра (секунды)
    timeout_sec: float = 0.5

    # Куда отправлять склеенный результат
    target: str = "gui"

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM для выходного склеенного кадра."""
        return {
            f"stitched_{self.camera_id}": (self.resolution_height, self.resolution_width, 3),
            "coll": 1,
        }
