"""MaskToFramePlugin -- мост: одноканальная маска → BGR-кадр (для дисплея).

Дисплей по конвенции показывает item['frame'] (3ch BGR). Бинарная маска hsv_mask
лежит в item['mask'] (1ch) — её не видно на дисплее. Этот плагин кладёт маску в
item['frame'] как BGR, чтобы вывести её на отдельный дисплей (визуальный тюнинг маски).

Display-only ветка: не используется в пути датасета. Stateless → thread_safe=True.
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

from .registers import MaskToFrameRegisters


@register_plugin("mask_to_frame", category="processing", description="Маска (1ch) → BGR-кадр для дисплея")
class MaskToFramePlugin(ProcessModulePlugin):
    """item[source_key] (маска) → item['frame'] (BGR), чтобы показать маску на дисплее."""

    name = "mask_to_frame"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска (1ch)"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Маска как BGR-кадр"),
    ]

    register_class = MaskToFrameRegisters

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: MaskToFrameRegisters = self._init_register(ctx)
        ctx.log_info(f"MaskToFramePlugin: source_key={self._reg.source_key}")

    @for_each
    def process(self, item: dict) -> dict | None:
        mask = item.get(self._reg.source_key)
        if mask is None:
            return None
        if mask.ndim == 2:
            bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        elif mask.ndim == 3 and mask.shape[2] == 1:
            bgr = cv2.cvtColor(mask[:, :, 0], cv2.COLOR_GRAY2BGR)
        else:
            bgr = mask  # уже 3-канальное
        return {**item, "frame": bgr}
