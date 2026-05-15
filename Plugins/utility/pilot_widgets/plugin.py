"""PilotWidgetsPlugin — тестовый стенд для проверки form-фабрики.

Самодостаточный плагин (без data flow). Worker LOOP каждые time_value секунд
читает все регистры:
    enabled    — гейтит инкремент счётчика
    info       — гейтит лог "[label_text] tick #N / paused"
    time_value — базовый интервал
    mode       — множитель интервала (fast=0.5x, normal=1x, slow=2x)
    multiplier — приращение счётчика за tick
    counter_max — лимит счётчика (после сброс)
    label_text — префикс лога
    color/notes/data_file/status_info/admin_only — публикуются в state_proxy
        для проверки worker→GUI пути через TopologyBridge.
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

_MODE_FACTOR: dict[str, float] = {"fast": 0.5, "normal": 1.0, "slow": 2.0}


@register_plugin(
    "pilot_widgets",
    category="utility",
    description="Тестовый стенд form-фабрики: все виды виджетов + worker LOOP",
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
        # Счётчик — float (multiplier может быть нецелым).
        self._tick_value: float = 0.0
        self._tick_count: int = 0

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
            f"time_value={self._reg.time_value}s, mode={self._reg.mode})"
        )

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(f"PilotWidgetsPlugin остановлен (total ticks={self._tick_count}, value={self._tick_value:.2f})")

    def _loop(self, stop_event, pause_event) -> None:
        while not stop_event.is_set():
            if pause_event and pause_event.is_set():
                time.sleep(0.05)
                continue

            # enabled гейтит инкремент.
            if self._reg.enabled:
                self._tick_count += 1
                self._tick_value += float(self._reg.multiplier)
                # counter_max=0 → без лимита; иначе сбрасываем по достижении.
                if self._reg.counter_max > 0 and self._tick_value >= self._reg.counter_max:
                    self._tick_value = 0.0
                    self._tick_count = 0

            # info гейтит лог.
            if self._reg.info:
                prefix = self._reg.label_text or "pilot_widgets"
                status = f"tick #{self._tick_count} value={self._tick_value:.2f}" if self._reg.enabled else "paused"
                self._ctx.log_info(f"[{prefix}] {status} mode={self._reg.mode}")

            self._publish_state()

            # Интервал = time_value * mode_factor (fast/normal/slow).
            factor = _MODE_FACTOR.get(self._reg.mode, 1.0)
            interval = max(0.1, float(self._reg.time_value) * factor)
            # stop_event.wait не принимает доли меньше 0.1 надёжно на всех платформах,
            # но для пилота это устраивает.
            if stop_event.wait(interval):
                return

    def _publish_state(self) -> None:
        """Публикация всех полей регистра в state_proxy (worker→GUI)."""
        if self._state_proxy is None:
            return
        path = f"processes.{self._ctx.process_name}.state"
        self._state_proxy.merge(
            path,
            {
                # Производное состояние worker'а
                "tick_count": self._tick_count,
                "tick_value": round(self._tick_value, 2),
                # Полный снимок регистра (для отладки GUI←worker пути)
                "enabled": self._reg.enabled,
                "info": self._reg.info,
                "time_value": self._reg.time_value,
                "counter_max": self._reg.counter_max,
                "multiplier": self._reg.multiplier,
                "mode": self._reg.mode,
                "color": list(self._reg.color),
                "label_text": self._reg.label_text,
                "notes": self._reg.notes,
                "data_file": str(self._reg.data_file),
                "status_info": self._reg.status_info,
                "admin_only": self._reg.admin_only,
            },
        )
