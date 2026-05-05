"""FrameCounterPlugin — приёмник frame_ready для проверки IPC.

Считает полученные кадры и логирует FPS каждые N секунд.
Минимальный consumer для доказательства что frame flow работает.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


@register_plugin(
    "frame_counter", category="processing", description="Счётчик полученных кадров + FPS лог"
)
class FrameCounterPlugin(ProcessModulePlugin):
    """Принимает frame_ready, считает кадры, логирует FPS."""

    name = "frame_counter"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр"),
    ]
    outputs = []
    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: регистрация handler-а для frame_ready."""
        cfg = ctx.config
        self._log_interval: float = cfg.get("log_interval_sec", 5.0)
        self._frame_count: int = 0
        self._last_log_time: float = time.monotonic()
        self._ctx = ctx

        # Регистрируем handler для входящих frame_ready сообщений
        ctx.router_manager.register_message_handler(
            key="frame_ready",
            handler=self._on_frame_ready,
            expects_full_message=True,
        )
        ctx.log_info("FrameCounterPlugin: handler frame_ready зарегистрирован")

    def start(self, ctx: PluginContext) -> None:
        """Плагин-слушатель, worker не нужен."""
        ctx.log_info("FrameCounterPlugin: запущен (ожидание frame_ready)")

    def shutdown(self, ctx: PluginContext) -> None:
        """Финальная статистика."""
        ctx.log_info(f"FrameCounterPlugin: shutdown. Всего кадров: {self._frame_count}")

    def _on_frame_ready(self, msg: dict) -> None:
        """Handler для frame_ready: инкремент + периодический FPS лог."""
        self._frame_count += 1

        now = time.monotonic()
        elapsed = now - self._last_log_time
        if elapsed >= self._log_interval:
            fps = self._frame_count / elapsed if elapsed > 0 else 0
            self._ctx.log_info(
                f"FrameCounterPlugin: {self._frame_count} кадров, "
                f"~{fps:.1f} FPS (за {elapsed:.1f}с)"
            )
            # Сбрасываем счётчик для расчёта FPS за окно
            self._frame_count = 0
            self._last_log_time = now
