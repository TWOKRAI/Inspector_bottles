"""HsvMaskPlugin — HSV-маска по цвету (атомарный плагин).

В отличие от color_mask, НЕ затирает кадр: добавляет item["mask"] (бинарная маска
uint8 1ch), а item["frame"] остаётся оригинальным — нужен дальше для рисования контура.
Слайдеры HSV — live через register.
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

from .registers import HsvMaskRegisters


@register_plugin("hsv_mask", category="processing", description="HSV-маска по цвету (кадр сохраняется)")
class HsvMaskPlugin(ProcessModulePlugin):
    """BGR → HSV → inRange → item['mask']; оригинальный кадр сохраняется."""

    name = "hsv_mask"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска (uint8)"),
    ]

    commands = {}
    register_class = HsvMaskRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import HsvMaskPluginConfig

        return HsvMaskPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: HsvMaskRegisters = self._init_register(ctx)
        ctx.log_info(
            f"HsvMaskPlugin: HSV [{self._reg.h_min},{self._reg.s_min},{self._reg.v_min}]-"
            f"[{self._reg.h_max},{self._reg.s_max},{self._reg.v_max}]"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        """Добавить бинарную маску по HSV-диапазону. Кадр не меняется."""
        frame = item.get("frame")
        if frame is None:
            return None
        r = self._reg
        lower = np.array([r.h_min, r.s_min, r.v_min], dtype=np.uint8)
        upper = np.array([r.h_max, r.s_max, r.v_max], dtype=np.uint8)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        return {**item, "mask": mask}
