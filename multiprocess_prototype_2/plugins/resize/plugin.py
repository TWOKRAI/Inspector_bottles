"""ResizePlugin -- масштабирование BGR-кадра.

Processing-плагин: process(items) -> items с cv2.resize.
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

# Маппинг интерполяции
_INTERP_MAP: dict[str, int] = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "area": cv2.INTER_AREA,
}


@register_plugin("resize", category="processing", description="Масштабирование BGR-кадра")
class ResizePlugin(ProcessModulePlugin):
    """Масштабирование кадра через cv2.resize."""

    name = "resize"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Масштабированный BGR-кадр"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Параметры ресайза из конфига."""
        cfg = ctx.config
        self._scale_factor: float = cfg.get("scale_factor", 1.0)
        self._target_width: int = cfg.get("target_width", 0)
        self._target_height: int = cfg.get("target_height", 0)
        self._interp: int = _INTERP_MAP.get(cfg.get("interpolation", "linear"), cv2.INTER_LINEAR)

        ctx.log_info(
            f"ResizePlugin: scale={self._scale_factor}, "
            f"target={self._target_width}x{self._target_height}"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        """Масштабирование одного кадра."""
        frame = item.get("frame")
        if frame is None:
            return None

        # Вычисляем target size
        if self._target_width > 0 and self._target_height > 0:
            new_w, new_h = self._target_width, self._target_height
        else:
            h, w = frame.shape[:2]
            new_w = max(1, int(w * self._scale_factor))
            new_h = max(1, int(h * self._scale_factor))

        resized = cv2.resize(frame, (new_w, new_h), interpolation=self._interp)
        return {**item, "frame": resized, "width": new_w, "height": new_h}
