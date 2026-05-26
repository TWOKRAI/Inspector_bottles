"""BlurPlugin — GaussianBlur размытие BGR-кадра.

Processing-плагин: process(items) -> items с cv2.GaussianBlur.
Форма кадра сохраняется. Все метаданные пробрасываются без изменений.
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


@register_plugin("blur", category="processing", description="GaussianBlur размытие BGR-кадра")
class BlurPlugin(ProcessModulePlugin):
    """Размытие BGR-кадра через cv2.GaussianBlur (форма сохраняется)."""

    name = "blur"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Размытый BGR-кадр"),
    ]

    commands = {}

    def __init__(self) -> None:
        super().__init__()
        # Параметры размытия — перезаписываются в configure()
        self._kernel_size: int = 5
        self._sigma: float = 0.0

    def configure(self, ctx: PluginContext) -> None:
        """Настройка параметров GaussianBlur из ctx.config."""
        kernel_size = int(ctx.config.get("kernel_size", 5))
        sigma = float(ctx.config.get("sigma", 0.0))

        # Валидация: kernel_size должен быть нечётным и положительным
        if kernel_size <= 0:
            ctx.log_error(
                f"BlurPlugin: kernel_size={kernel_size} должен быть > 0, используется значение по умолчанию 5"
            )
            kernel_size = 5
        elif kernel_size % 2 == 0:
            # Увеличиваем на 1, чтобы сделать нечётным
            kernel_size += 1
            ctx.log_info(f"BlurPlugin: kernel_size чётный — скорректирован до {kernel_size}")

        self._kernel_size = kernel_size
        self._sigma = sigma

        ctx.log_info(f"BlurPlugin: configured kernel_size={self._kernel_size}, sigma={self._sigma}")

    @for_each
    def process(self, item: dict) -> dict | None:
        """Применяет GaussianBlur к кадру. Все метаданные пробрасываются."""
        frame = item.get("frame")
        if frame is None:
            return None

        blurred = cv2.GaussianBlur(
            frame,
            (self._kernel_size, self._kernel_size),
            self._sigma,
        )
        return {**item, "frame": blurred}
