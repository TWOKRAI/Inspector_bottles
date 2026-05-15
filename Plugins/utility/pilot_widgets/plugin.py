"""PilotWidgetsPlugin — тестовый стенд для проверки form-фабрики.

Самодостаточный плагин (без data flow). worker LOOP каждые self._reg.time_value
секунд читает регистры:
    enabled — гейтит инкремент счётчика (работа)
    info    — гейтит лог "[pilot_widgets] tick #N / paused"
Tick-счётчик публикуется в state_proxy (worker→GUI путь через TopologyBridge).
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

    # commands и cmd_set_config — наследуются из ProcessModulePlugin.
    # При наличии register_class фреймворк автоматически регистрирует
    # generic set_config handler в CommandManager.

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: register + counter."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)
        self._state_proxy = ctx.state_proxy
        # Интервал, счётчик и логирование — динамически из self._reg на каждой итерации loop.
        # enabled гейтит инкремент счётчика, info гейтит лог.
        self._tick_count = 0

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: запустить worker LOOP."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "pilot_widgets_worker",
            self._loop,
            cfg,
            auto_start=True,
        )
        ctx.log_info(
            f"PilotWidgetsPlugin запущен "
            f"(enabled={self._reg.enabled}, info={self._reg.info}, "
            f"time_value={self._reg.time_value}s)"
        )

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(f"PilotWidgetsPlugin остановлен (total ticks={self._tick_count})")

    def _loop(self, stop_event, pause_event) -> None:
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                time.sleep(0.05)
                continue

            # enabled гейтит работу — инкрементируем счётчик только когда включено.
            if self._reg.enabled:
                self._tick_count += 1

            # info гейтит лог — независимо от enabled.
            if self._reg.info:
                status = f"tick #{self._tick_count}" if self._reg.enabled else "paused"
                self._ctx.log_info(f"[pilot_widgets] {status} (interval={self._reg.time_value}s)")

            self._publish_state()

            # Интервал — динамически из регистра. Изменение time_value в GUI
            # применяется на следующей итерации loop.
            interval = max(1, int(self._reg.time_value))
            if stop_event.wait(interval):
                return

    def _publish_state(self) -> None:
        """Публикация tick-счётчика в state_proxy для worker→GUI пути."""
        if self._state_proxy is None:
            return
        path = f"processes.{self._ctx.process_name}.state"
        self._state_proxy.merge(
            path,
            {
                "tick_count": self._tick_count,
                "enabled": self._reg.enabled,
                "info": self._reg.info,
                "time_value": self._reg.time_value,
            },
        )
