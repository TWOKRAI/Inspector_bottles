"""TickSourcePlugin — тривиальный генератор для examples/minimal_app.

Второй потребитель фреймворка (после прототипа) — forcing function против
Inspector-специфики в «универсальном» app_module (Ф5.11). Плагин намеренно
минимален: worker в режиме LOOP логирует счётчик каждые ``interval_sec`` секунд.
Ни камеры, ни SHM, ни реактивного state — чистый headless-tick, доказывающий, что
«рыба» бутится на framework-дефолтах (GenericProcess + ProcessManagerProcess).

Ф5.13: каждый тик также уходит межпроцессным сообщением получателю (``target``,
дефолт ``console_sink``) — доказывает реальный IPC между двумя процессами «рыбы»
(ревью 5.11 отметило, что пустой ``wires: []`` этого не демонстрирует). Сообщение —
``type="event"`` + явный ``queue_type="system"`` + payload под ``data`` — тот же
формат, что у прикладных событий фреймворка: ``state.changed``
(``state_store_module/manager/delta_dispatcher.py``) и ``observability.record``
(``channel_routing_module/observability/record_forward_channel.py``). ВАЖНО:
``queue_type="system"`` — это выбор ФИЗИЧЕСКОЙ очереди доставки (её опрашивает
``SystemThreads`` получателя независимо от того, есть ли у него data-pipeline
воркеры — обычная "data"-очередь опрашивается ``DataReceiver``, который создаётся
только при наличии processing-плагинов и здесь не гарантирован). Это НЕ то же
самое, что ``type="command"``/``type="system"`` (control-plane kind, зарезервирован
за системными сообщениями ProcessManager/heartbeat) — ``type="event"`` явно метит
сообщение как прикладное, что важно для будущих QoS-профилей по kind (Ф7 G.4:
system-kind = never-drop, event-kind получит свой профиль).
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
        self._target = ctx.config.get("target", "console_sink")
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
            self._send_tick()
            stop_event.wait(self._interval)

    def _send_tick(self) -> None:
        """Отправить тик получателю межпроцессно (IPC-доказательство Ф5.13)."""
        if not self._ctx.send_message:
            return
        ok = self._ctx.send_message(
            self._target,
            {
                "type": "event",
                "queue_type": "system",
                "command": "tick",
                "data": {"count": self._count, "payload": self._message},
            },
        )
        if not ok:
            self._ctx.log_error(f"TickSourcePlugin: send_message('{self._target}') failed (тик #{self._count})")
