"""HeartbeatPlugin — периодический лог для проверки работоспособности системы.

Простейший плагин: создаёт один worker в режиме LOOP,
который каждые `interval_sec` секунд логирует сообщение.
Используется для проверки что фреймворк загружается и работает.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.registry import (
    register_plugin,
)
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


@register_plugin("heartbeat", category="utility", description="Периодический heartbeat-лог")
class HeartbeatPlugin(ProcessModulePlugin):
    """Логирует heartbeat каждые N секунд через WorkerManager."""

    name = "heartbeat"
    category = "utility"
    inputs = []
    outputs = []

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: читаем конфиг."""
        self._interval = ctx.config.get("interval_sec", 2.0)
        self._message = ctx.config.get("message", "alive")
        self._count = 0
        self._ctx = ctx

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: создаём worker."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "heartbeat_worker", self._loop, cfg, auto_start=True
        )
        ctx.log_info(f"HeartbeatPlugin запущен (интервал {self._interval}с)")

    def shutdown(self, ctx: PluginContext) -> None:
        """Останов плагина."""
        ctx.log_info(f"HeartbeatPlugin остановлен (всего {self._count} heartbeats)")

    def _loop(self, stop_event, pause_event) -> None:
        """Worker loop: логирует heartbeat с заданным интервалом."""
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                time.sleep(0.05)
                continue
            self._count += 1
            self._ctx.log_info(f"[heartbeat #{self._count}] {self._message}")
            stop_event.wait(self._interval)
