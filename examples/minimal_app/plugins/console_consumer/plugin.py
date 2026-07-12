"""ConsoleConsumerPlugin — приёмник тиков для examples/minimal_app (Ф5.13).

Второй процесс «рыбы»: живой IPC-приёмник, доказывающий, что сообщения от
``tick_source`` реально доходят между двумя ОС-процессами (не только boot, как
было в Ф5.11 — ревью отметило пустой ``wires: []``). Регистрирует межпроцессный
обработчик через ``ctx.router_manager.register_message_handler`` — тот же
транспорт (``type="event"`` + явный ``queue_type="system"``), что используют
``state.changed`` (``state_store_module/manager/delta_dispatcher.py``) и
``observability.record`` (``channel_routing_module/observability/record_forward_channel.py``) —
и считает полученные тики.

Счётчик доступен снаружи через команду ``consumer_status`` (авто-регистрация
через ``commands``) — CI-smoke опрашивает её через backend_ctl driver, чтобы
подтвердить доставку.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)


@register_plugin("console_consumer", category="utility", description="Приёмник тиков (minimal_app, IPC-доказательство)")
class ConsoleConsumerPlugin(ProcessModulePlugin):
    """Считает межпроцессные тики от ``tick_source`` и логирует каждый приём."""

    name = "console_consumer"
    category = "utility"
    inputs: list = []
    outputs: list = []

    #: Авто-регистрация команды в CommandManager (ProcessModulePlugin._auto_register_commands).
    commands = {"consumer_status": "cmd_status"}

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._received = 0
        self._last_payload: str | None = None
        if ctx.router_manager is not None:
            ctx.router_manager.register_message_handler("tick", self._on_tick)

    def _on_tick(self, message: dict) -> None:
        """Обработчик события ``command=="tick"`` (event_dispatcher, полное сообщение).

        Payload — под ``data`` (Dict-at-Boundary, тот же конверт-контракт, что у
        ``state.changed``/``observability.record``), не на верхнем уровне сообщения.
        """
        self._received += 1
        data = message.get("data") or {}
        self._last_payload = data.get("payload")
        self._ctx.log_info(f"[console_consumer] тик #{self._received} принят: {self._last_payload}")

    def cmd_status(self, _data: dict) -> dict:
        """Снапшот счётчика — читает CI-smoke через ``send_command`` (доказательство IPC)."""
        return {"status": "ok", "received": self._received, "last_payload": self._last_payload}

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(f"ConsoleConsumerPlugin остановлен (всего принято {self._received} тиков)")
