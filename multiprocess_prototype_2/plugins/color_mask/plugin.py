"""ColorMaskPlugin — HSV-маска по цвету.

Processing-плагин: process(items) -> items с cv2.inRange.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
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

from .registers import ColorMaskRegisters


@register_plugin("color_mask", category="processing", description="HSV-маска по цвету")
class ColorMaskPlugin(ProcessModulePlugin):
    """HSV-маска по цвету с runtime-настройкой через регистр."""

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
        """Настройка: register managed (GUI) или локальный (defaults)."""
        cfg = ctx.config
        self._ctx = ctx

        # Register: managed (RegistersManager → GUI видит) или локальный
        self._reg = (
            ctx.registers.get_register(self.name)
            if ctx.registers is not None
            else None
        ) or ColorMaskRegisters()

        # YAML overrides → синхронизируем в register
        for field in type(self._reg).model_fields:
            if field in cfg:
                setattr(self._reg, field, cfg[field])

        ctx.log_info(
            f"ColorMaskPlugin: HSV "
            f"[{self._reg.h_min},{self._reg.s_min},{self._reg.v_min}]-"
            f"[{self._reg.h_max},{self._reg.s_max},{self._reg.v_max}]"
        )

    def start(self, ctx: PluginContext) -> None:
        """No-op — обработка через process()."""

    # --- Команды ---

    def set_hsv_range(self, data: dict) -> dict:
        """Обновить HSV-диапазон в runtime."""
        for field in type(self._reg).model_fields:
            if field in data:
                setattr(self._reg, field, data[field])

        self._ctx.log_info(
            f"ColorMaskPlugin: HSV обновлён "
            f"[{self._reg.h_min},{self._reg.s_min},{self._reg.v_min}]-"
            f"[{self._reg.h_max},{self._reg.s_max},{self._reg.v_max}]"
        )
        return {"status": "ok"}

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """BGR -> HSV -> inRange -> маска (BGR 3ch для pipeline совместимости)."""
        frame = item.get("frame")
        if frame is None:
            return None

        # HSV-пороги всегда из register
        lower = np.array([self._reg.h_min, self._reg.s_min, self._reg.v_min], dtype=np.uint8)
        upper = np.array([self._reg.h_max, self._reg.s_max, self._reg.v_max], dtype=np.uint8)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        return {**item, "frame": mask_bgr}
