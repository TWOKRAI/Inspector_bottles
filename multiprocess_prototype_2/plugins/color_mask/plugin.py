"""ColorMaskPlugin -- HSV-маска по цвету.

Processing-плагин: process(items) -> items с cv2.inRange.
Пороги настраиваются через:
  - RegistersManager (если регистр color_mask доступен) — обновляются из GUI автоматически
  - Команда set_hsv_range (fallback, legacy)
  - Config defaults (если ни регистра, ни команды)
"""

from __future__ import annotations

from typing import Any

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
    """HSV-маска по цвету с runtime-настройкой через регистр или команду."""

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

    def register_schema(self) -> Any | None:
        """Вернуть ColorMaskRegisters для RegistersManager."""
        try:
            from multiprocess_prototype_2.registers.color_mask import ColorMaskRegisters
            return ColorMaskRegisters()
        except ImportError:
            return None

    def configure(self, ctx: PluginContext) -> None:
        """Настройка HSV-параметров: из регистра или config defaults."""
        cfg = ctx.config
        self._ctx = ctx

        # Попытка получить регистр (если RegistersManager доступен)
        self._reg = None
        if ctx.registers is not None:
            self._reg = ctx.registers.get_register(self.name)

        if self._reg is not None:
            # Регистр есть — HSV-пороги читаются из него (всегда актуальные)
            # Переопределить defaults из config если заданы
            for field, cfg_key in [
                ("min_h", "h_min"), ("max_h", "h_max"),
                ("min_s", "s_min"), ("max_s", "s_max"),
                ("min_v", "v_min"), ("max_v", "v_max"),
            ]:
                if cfg_key in cfg:
                    setattr(self._reg, field, cfg[cfg_key])

            ctx.log_info(
                f"ColorMaskPlugin: HSV из регистра "
                f"[{self._reg.min_h},{self._reg.min_s},{self._reg.min_v}]-"
                f"[{self._reg.max_h},{self._reg.max_s},{self._reg.max_v}]"
            )
        else:
            # Graceful degradation — fallback на config/hardcode
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
            ctx.log_info(f"ColorMaskPlugin: HSV из config [{self._lower}]-[{self._upper}]")

    def start(self, ctx: PluginContext) -> None:
        """No-op -- обработка через process()."""

    # --- Команды ---

    def set_hsv_range(self, data: dict) -> dict:
        """Обновить HSV-диапазон в runtime (legacy fallback)."""
        if self._reg is not None:
            # Через регистр — изменения автоматически видны в process()
            for field, key in [
                ("min_h", "h_min"), ("max_h", "h_max"),
                ("min_s", "s_min"), ("max_s", "s_max"),
                ("min_v", "v_min"), ("max_v", "v_max"),
            ]:
                if key in data:
                    setattr(self._reg, field, data[key])
            self._ctx.log_info(
                f"ColorMaskPlugin: HSV обновлён через регистр "
                f"[{self._reg.min_h},{self._reg.min_s},{self._reg.min_v}]-"
                f"[{self._reg.max_h},{self._reg.max_s},{self._reg.max_v}]"
            )
            return {"status": "ok"}
        else:
            # Legacy: обновить numpy arrays
            if "h_min" in data: self._lower[0] = data["h_min"]
            if "h_max" in data: self._upper[0] = data["h_max"]
            if "s_min" in data: self._lower[1] = data["s_min"]
            if "s_max" in data: self._upper[1] = data["s_max"]
            if "v_min" in data: self._lower[2] = data["v_min"]
            if "v_max" in data: self._upper[2] = data["v_max"]
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

        # HSV-пороги: из регистра (auto-update) или numpy arrays
        if self._reg is not None:
            lower = np.array([self._reg.min_h, self._reg.min_s, self._reg.min_v], dtype=np.uint8)
            upper = np.array([self._reg.max_h, self._reg.max_s, self._reg.max_v], dtype=np.uint8)
        else:
            lower, upper = self._lower, self._upper

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        return {**item, "frame": mask_bgr}
