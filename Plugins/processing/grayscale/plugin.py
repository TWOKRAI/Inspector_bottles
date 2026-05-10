"""GrayscalePlugin -- BGR -> Grayscale.

Processing-плагин: process(items) -> items с cv2.cvtColor.
Результат -- BGR 3ch (для совместимости с stitcher и другими плагинами).
Метаданные координат пробрасываются без изменений.
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin


@register_plugin("grayscale", category="processing", description="Конвертация BGR -> Grayscale")
class GrayscalePlugin(ProcessModulePlugin):
    """Конвертация BGR -> Grayscale (3ch BGR для совместимости)."""

    name = "grayscale"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Grayscale-кадр (BGR 3ch)"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка (параметров нет -- stateless)."""
        ctx.log_info("GrayscalePlugin: configured")

    @for_each
    def process(self, item: dict) -> dict | None:
        """BGR -> Gray -> BGR 3ch. Все метаданные пробрасываются."""
        frame = item.get("frame")
        if frame is None:
            return None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        return {**item, "frame": gray_bgr}
