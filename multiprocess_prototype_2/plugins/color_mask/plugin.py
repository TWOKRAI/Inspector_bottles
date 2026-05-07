"""ColorMaskPlugin — HSV-маска по цвету.

Processing-плагин: process(items) -> items с cv2.inRange.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import time
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

    register_class = ColorMaskRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # StateProxy для публикации метрик (может быть None)
        self._state_proxy = ctx.state_proxy

        # Счётчики метрик
        self._processed_count: int = 0
        self._latency_sum_ms: float = 0.0
        self._latency_count: int = 0
        self._last_publish: float = time.monotonic()

        ctx.log_info(
            f"ColorMaskPlugin: HSV "
            f"[{self._reg.h_min},{self._reg.s_min},{self._reg.v_min}]-"
            f"[{self._reg.h_max},{self._reg.s_max},{self._reg.v_max}]"
        )

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
    def _process_item(self, item: dict) -> dict | None:
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

    def process(self, items: list[dict]) -> list[dict]:
        """Обёртка: замер latency + публикация метрик в StateStore раз в секунду."""
        t0 = time.monotonic()
        result = self._process_item(items)
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Обновляем накопители
        self._processed_count += len(items)
        self._latency_sum_ms += elapsed_ms
        self._latency_count += 1

        # Публикуем раз в секунду
        now = time.monotonic()
        if now - self._last_publish >= 1.0:
            self._publish_state()
            self._last_publish = now

        return result

    def _publish_state(self) -> None:
        """Опубликовать метрики в StateStore."""
        if self._state_proxy is None:
            return

        avg_latency = (
            self._latency_sum_ms / self._latency_count
            if self._latency_count > 0 else 0.0
        )
        path = f"processes.{self._ctx.process_name}.state"
        self._state_proxy.merge(path, {
            "status": "running",
            "processed_count": self._processed_count,
            "avg_latency_ms": round(avg_latency, 2),
        })

        # Сбросить накопители для следующего интервала
        self._latency_sum_ms = 0.0
        self._latency_count = 0
