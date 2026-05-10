"""Конфиг StitcherPlugin — параметры склейки."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import PluginConfig


@register_schema("StitcherPluginConfigV2")
class StitcherPluginConfig(PluginConfig):
    """Конфиг плагина склейки регионов.

    Собирает region_processed от нескольких процессов,
    буферизует по seq_id, склеивает на canvas по координатам.
    """

    plugin_class: str = (
        "Plugins.processing.stitcher.plugin.StitcherPlugin"
    )

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
