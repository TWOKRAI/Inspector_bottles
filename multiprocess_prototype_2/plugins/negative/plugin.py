"""NegativePlugin -- инверсия цвета BGR-кадра.

Processing-плагин: process(items) -> items с 255 - frame.
Метаданные координат пробрасываются без изменений.
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("negative", category="processing", description="Инверсия цвета (негатив)")
class NegativePlugin(ProcessModulePlugin):
    """Инверсия цвета: 255 - frame."""

    name = "negative"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-регион"),
    ]
    outputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Инвертированный BGR-регион"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка (параметров нет -- stateless)."""
        ctx.log_info("NegativePlugin: configured")

    def start(self, ctx: PluginContext) -> None:
        """No-op -- обработка через process()."""

    @for_each
    def process(self, item: dict) -> dict | None:
        """Инверсия: 255 - frame. Все метаданные пробрасываются."""
        frame = item.get("frame")
        if frame is None:
            return None
        return {**item, "frame": np.asarray(255 - frame, dtype=np.uint8)}
