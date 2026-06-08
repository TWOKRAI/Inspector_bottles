"""ColorConvertPlugin — конвертация цветовых каналов кадра (BGR ↔ RGB).

Processing-плагин: process(items) -> items с переставленными каналами R/B.
Нужен, когда источник отдаёт кадр в одном порядке каналов, а дисплей/
следующая нода ожидает другой (классический случай — Bayer-демозаик
промышленной камеры даёт RGB-порядок, а дисплей настроен на BGR).

Операция BGR↔RGB — это один и тот же swap каналов R и B, поэтому оба
режима (``bgr2rgb`` / ``rgb2bgr``) выполняют ``cv2.COLOR_BGR2RGB``.
Метаданные (координаты, frame_id, ...) пробрасываются без изменений.
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


@register_plugin(
    "color_convert",
    category="processing",
    description="Конвертация цветовых каналов кадра (BGR ↔ RGB)",
)
class ColorConvertPlugin(ProcessModulePlugin):
    """Перестановка каналов R/B (BGR ↔ RGB)."""

    name = "color_convert"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр с переставленными R/B"),
    ]

    commands: dict[str, str] = {}

    def configure(self, ctx: PluginContext) -> None:
        """Прочитать режим (для логирования; операция одна — swap R/B)."""
        self._mode: str = ctx.config.get("mode", "bgr2rgb")
        ctx.log_info(f"ColorConvertPlugin: configured (mode={self._mode})")

    @for_each
    def process(self, item: dict) -> dict | None:
        """Поменять местами каналы R и B. Метаданные пробрасываются."""
        frame = item.get("frame")
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            return None
        return {**item, "frame": cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)}
