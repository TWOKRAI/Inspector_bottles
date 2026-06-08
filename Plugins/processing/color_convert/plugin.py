"""ColorConvertPlugin — конвертация цветовых каналов кадра (BGR ↔ RGB и др.).

Processing-плагин: process(items) -> items с конвертированным кадром. Режим
выбирается выпадающим списком в инспекторе ноды (ColorConvertRegisters.mode,
live). Нужен, когда источник отдаёт кадр в одном порядке/пространстве, а дисплей
ожидает другой (классика — Bayer-демозаик промышленной камеры даёт RGB-порядок,
а дисплей настроен на BGR → режим bgr2rgb).

Все режимы сохраняют 3-канальный кадр (grayscale конвертируется обратно в BGR).
Метаданные (координаты, frame_id, ...) пробрасываются без изменений.
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import ColorConvertRegisters

# Режим → cv2-код конвертации. None/grayscale обрабатываются отдельно (см. _convert).
_CV2_CODES: dict[str, int] = {
    "bgr2rgb": cv2.COLOR_BGR2RGB,
    "rgb2bgr": cv2.COLOR_RGB2BGR,
    "bgr2hsv": cv2.COLOR_BGR2HSV,
    "bgr2hls": cv2.COLOR_BGR2HLS,
    "bgr2lab": cv2.COLOR_BGR2Lab,
    "bgr2luv": cv2.COLOR_BGR2Luv,
    "bgr2yuv": cv2.COLOR_BGR2YUV,
    "bgr2ycrcb": cv2.COLOR_BGR2YCrCb,
    "bgr2xyz": cv2.COLOR_BGR2XYZ,
}


@register_plugin(
    "color_convert",
    category="processing",
    description="Конвертация цветовых каналов кадра (BGR ↔ RGB и др.)",
)
class ColorConvertPlugin(ProcessModulePlugin):
    """Конвертация цветовых каналов кадра по выбранному режиму."""

    name = "color_convert"
    category = "processing"
    thread_safe = True
    register_class = ColorConvertRegisters

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Конвертированный кадр (3 канала)"),
    ]

    commands: dict[str, str] = {}

    @classmethod
    def config_class(cls) -> type | None:
        from .config import ColorConvertConfig

        return ColorConvertConfig

    def configure(self, ctx: PluginContext) -> None:
        """Создать register (live-режим через выпадающий список в инспекторе)."""
        self._reg: ColorConvertRegisters = self._init_register(ctx)
        ctx.log_info(f"ColorConvertPlugin: configured (mode={self._reg.mode})")

    @for_each
    def process(self, item: dict) -> dict | None:
        """Конвертировать кадр по текущему режиму (читается из register live)."""
        frame = item.get("frame")
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            return None
        converted = self._convert(frame, self._reg.mode)
        return {**item, "frame": converted}

    @staticmethod
    def _convert(frame, mode: str):
        """Применить конвертацию; всегда возвращает 3-канальный кадр."""
        if mode == "none":
            return frame
        if mode == "bgr2gray":
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        code = _CV2_CODES.get(mode)
        if code is None:
            return frame
        return cv2.cvtColor(frame, code)
