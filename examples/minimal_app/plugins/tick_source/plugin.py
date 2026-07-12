"""TickSourcePlugin — тривиальный генератор для examples/minimal_app.

Второй потребитель фреймворка (после прототипа) — forcing function против
Inspector-специфики в «универсальном» app_module (Ф5.11). Плагин намеренно
минимален: worker в режиме LOOP логирует счётчик каждые ``interval_sec`` секунд.
Ни камеры, ни SHM, ни реактивного state — чистый headless-tick, доказывающий, что
«рыба» бутится на framework-дефолтах (GenericProcess + ProcessManagerProcess).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)


@register_plugin("tick_source", category="utility", description="Тривиальный tick-генератор (minimal_app)")
class TickSourcePlugin(ProcessModulePlugin):
    """Логирует tick каждые N секунд — минимальный headless-источник."""

    name = "tick_source"
    category = "utility"
    inputs: list = []
    outputs: list = []

    def configure(self, ctx: PluginContext) -> None:
        self._interval = float(ctx.config.get("interval_sec", 1.0))
        self._message = ctx.config.get("message", "tick")
        self._count = 0
        self._ctx = ctx

    def start(self, ctx: PluginContext) -> None:
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("tick_worker", self._loop, cfg, auto_start=True)
        ctx.log_info(f"TickSourcePlugin запущен (интервал {self._interval}с)")

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(f"TickSourcePlugin остановлен (всего {self._count} тиков)")

    def _loop(self, stop_event, pause_event) -> None:
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                stop_event.wait(0.05)
                continue
            self._count += 1
            self._ctx.log_info(f"[tick #{self._count}] {self._message}")
            stop_event.wait(self._interval)
