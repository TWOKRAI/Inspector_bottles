"""MorphologyPlugin — морфологическая чистка бинарной маски (атомарный плагин).

Вход: item["mask"] (от hsv_mask). Выход: item["mask"] — та же маска после
морфологии. Кадр (item["frame"]) пробрасывается без изменений.

Назначение в пайплайне калибровки: после hsv_mask маска красного содержит шум
(одиночные пиксели, рваные края). open «вырезает» только сплошные пятна-круги,
close заполняет дырки внутри них — на выходе чистая маска ровно из красных кругов.

Атомарность: НЕ детектирует, НЕ рисует — только морфология. Детекция вынесена
в contour_finder (модульность, как у hsv_mask / contour_draw).
"""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import MorphologyRegisters

# Карта формы ядра → константа OpenCV.
_SHAPES = {
    "ellipse": cv2.MORPH_ELLIPSE,
    "rect": cv2.MORPH_RECT,
    "cross": cv2.MORPH_CROSS,
}


@register_plugin("morphology", category="processing", description="Морфология бинарной маски (open/close/erode/dilate)")
class MorphologyPlugin(ProcessModulePlugin):
    """mask → морфологическая операция → mask (кадр сохраняется)."""

    name = "morphology"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Входная бинарная маска"),
    ]
    outputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Маска после морфологии"),
    ]

    commands = {}
    register_class = MorphologyRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import MorphologyPluginConfig

        return MorphologyPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: MorphologyRegisters = self._init_register(ctx)
        ctx.log_info(
            f"MorphologyPlugin: op={self._reg.operation}, shape={self._reg.kernel_shape}, "
            f"ksize={self._reg.kernel_size}, iters={self._reg.iterations}"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        """Применить морфологию к item['mask']. Кадр не трогаем."""
        mask = item.get("mask")
        if mask is None:
            return item  # маски нет — пробрасываем как есть
        op = self._reg.operation
        if op == "none":
            return item
        return {**item, "mask": self._apply(mask)}

    def _apply(self, mask: np.ndarray) -> np.ndarray:
        """Морфология по выбранной операции/ядру."""
        k = int(self._reg.kernel_size)
        if k < 1:
            k = 1
        if k % 2 == 0:
            k += 1  # нечётное ядро → симметричный центр
        shape = _SHAPES.get(self._reg.kernel_shape, cv2.MORPH_ELLIPSE)
        kernel = cv2.getStructuringElement(shape, (k, k))
        iters = max(1, int(self._reg.iterations))
        op = self._reg.operation
        if op == "erode":
            return cv2.erode(mask, kernel, iterations=iters)
        if op == "dilate":
            return cv2.dilate(mask, kernel, iterations=iters)
        if op == "open":
            return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=iters)
        if op == "close":
            return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=iters)
        # open_close: сначала убрать шум (open), затем заполнить дырки (close)
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=iters)
        return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel, iterations=iters)
