"""FrameCounterPlugin -- счётчик кадров + FPS лог.

Processing-плагин: process(items) -> items (pass-through с подсчётом).
Без декоратора @for_each -- нужен batch для FPS.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin


@register_plugin(
    "frame_counter", category="processing", description="Счётчик полученных кадров + FPS лог"
)
class FrameCounterPlugin(ProcessModulePlugin):
    """Считает кадры и логирует FPS каждые N секунд. Pass-through."""

    name = "frame_counter"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр"),
    ]
    outputs = []
    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка интервала логирования."""
        cfg = ctx.config
        self._log_interval: float = cfg.get("log_interval_sec", 5.0)
        self._frame_count: int = 0
        self._last_log_time: float = time.monotonic()
        self._ctx = ctx
        ctx.log_info("FrameCounterPlugin: configured")

    def shutdown(self, ctx: PluginContext) -> None:
        """Финальная статистика."""
        ctx.log_info(f"FrameCounterPlugin: shutdown. Всего кадров: {self._frame_count}")

    def process(self, items: list[dict]) -> list[dict]:
        """Подсчёт кадров + периодический FPS лог. Pass-through."""
        self._frame_count += len(items)

        now = time.monotonic()
        elapsed = now - self._last_log_time
        if elapsed >= self._log_interval:
            fps = self._frame_count / elapsed if elapsed > 0 else 0
            self._ctx.log_info(
                f"FrameCounterPlugin: {self._frame_count} кадров, "
                f"~{fps:.1f} FPS (за {elapsed:.1f}с)"
            )
            self._frame_count = 0
            self._last_log_time = now

        return items
