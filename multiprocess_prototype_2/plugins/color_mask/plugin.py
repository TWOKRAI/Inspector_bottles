"""ColorMaskPlugin -- HSV-маска по цвету.

Processing-плагин: process(items) -> items с cv2.inRange.
Пороги изменяются через команду set_hsv_range (runtime).
"""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("color_mask", category="processing", description="HSV-маска по цвету")
class ColorMaskPlugin(ProcessModulePlugin):
    """HSV-маска по цвету с runtime-настройкой порогов."""

    name = "color_mask"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W, 1)", description="Бинарная маска"),
    ]

    commands = {
        "set_hsv_range": "set_hsv_range",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка HSV-параметров."""
        cfg = ctx.config
        self._lower = np.array([
            cfg.get("h_min", 0),
            cfg.get("s_min", 50),
            cfg.get("v_min", 50),
        ], dtype=np.uint8)
        self._upper = np.array([
            cfg.get("h_max", 180),
            cfg.get("s_max", 255),
            cfg.get("v_max", 255),
        ], dtype=np.uint8)

        self._ctx = ctx
        ctx.log_info(f"ColorMaskPlugin: HSV [{self._lower}]-[{self._upper}]")

    def start(self, ctx: PluginContext) -> None:
        """No-op -- обработка через process()."""

    # --- Команды ---

    def set_hsv_range(self, data: dict) -> dict:
        """Обновить HSV-диапазон в runtime."""
        if "h_min" in data:
            self._lower[0] = data["h_min"]
        if "h_max" in data:
            self._upper[0] = data["h_max"]
        if "s_min" in data:
            self._lower[1] = data["s_min"]
        if "s_max" in data:
            self._upper[1] = data["s_max"]
        if "v_min" in data:
            self._lower[2] = data["v_min"]
        if "v_max" in data:
            self._upper[2] = data["v_max"]

        self._ctx.log_info(
            f"ColorMaskPlugin: HSV обновлён [{self._lower}]-[{self._upper}]"
        )
        return {"status": "ok", "lower": self._lower.tolist(), "upper": self._upper.tolist()}

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """BGR -> HSV -> inRange -> маска (BGR 3ch для pipeline совместимости)."""
        frame = item.get("frame")
        if frame is None:
            return None

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._lower, self._upper)
        # Маска как BGR 3ch для совместимости с pipeline
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        return {**item, "frame": mask_bgr}
