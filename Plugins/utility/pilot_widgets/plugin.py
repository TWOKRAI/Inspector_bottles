"""PilotWidgetsPlugin — тестовый стенд для проверки form-фабрики.

Самодостаточный плагин (без data flow): worker LOOP каждые `interval_sec`
секунд читает self._reg.enabled и логирует tick. Если включено — пишет
счётчик в state_proxy для проверки worker→GUI пути через TopologyBridge.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from .registers import PilotWidgetsRegisters


@register_plugin(
    "pilot_widgets",
    category="utility",
    description="Тестовый стенд form-фабрики: bool через CheckboxControl + worker LOOP",
)
class PilotWidgetsPlugin(ProcessModulePlugin):
    """Pilot-плагин для smoke-тестов form-фабрики."""

    name = "pilot_widgets"
    category = "utility"
    inputs = []
    outputs = []
    register_class = PilotWidgetsRegisters

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: register + counters."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)
        self._state_proxy = ctx.state_proxy
        self._interval = float(ctx.config.get("interval_sec", 1.0))
        self._tick_count = 0
        self._active_tick_count = 0

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: запустить worker LOOP."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "pilot_widgets_worker",
            self._loop,
            cfg,
            auto_start=True,
        )
        ctx.log_info(f"PilotWidgetsPlugin запущен (interval={self._interval}s, enabled={self._reg.enabled})")

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(
            f"PilotWidgetsPlugin остановлен (total ticks={self._tick_count}, active ticks={self._active_tick_count})"
        )

    def _loop(self, stop_event, pause_event) -> None:
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                time.sleep(0.05)
                continue

            self._tick_count += 1

            if self._reg.enabled:
                self._active_tick_count += 1
                self._ctx.log_info(
                    f"[pilot_widgets tick #{self._tick_count}] active (active={self._active_tick_count})"
                )
            else:
                self._ctx.log_info(f"[pilot_widgets tick #{self._tick_count}] paused")

            self._publish_state()
            stop_event.wait(self._interval)

    def _publish_state(self) -> None:
        """Публикация tick-счётчиков в state_proxy для worker→GUI пути."""
        if self._state_proxy is None:
            return
        path = f"processes.{self._ctx.process_name}.state"
        self._state_proxy.merge(
            path,
            {
                "tick_count": self._tick_count,
                "active_tick_count": self._active_tick_count,
                "enabled": self._reg.enabled,
            },
        )
