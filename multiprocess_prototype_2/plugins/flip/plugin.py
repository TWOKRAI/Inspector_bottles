"""FlipPlugin -- вертикальный переворот BGR-кадра.

Processing-плагин: process(items) -> items с cv2.flip(frame, 0).
Метаданные координат пробрасываются без изменений.
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("flip", category="processing", description="Вертикальный переворот кадра")
class FlipPlugin(ProcessModulePlugin):
    """Вертикальный переворот: cv2.flip(frame, 0)."""

    name = "flip"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-регион"),
    ]
    outputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Перевёрнутый BGR-регион"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка (параметров нет -- stateless)."""
        ctx.log_info("FlipPlugin: configured")

    def start(self, ctx: PluginContext) -> None:
        """No-op -- обработка через process()."""

    @for_each
    def process(self, item: dict) -> dict | None:
        """Переворот: cv2.flip(frame, 0). Все метаданные пробрасываются."""
        frame = item.get("frame")
        if frame is None:
            return None
        return {**item, "frame": cv2.flip(frame, 0)}
