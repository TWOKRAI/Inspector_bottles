"""BeltReaderPlugin — фикстура тестера Task 2.0 (independent RED).

Подписывается на ``sim.belt.*`` в ``configure()`` (ДО того, как тест триггерит
``trigger_set`` у writer'а — порядок обеспечивает сам тест, опрашивая
``system_overview`` до running перед отправкой команды) и копит дельты для
опроса снаружи через команды ``received``/``get_belt``.

``sync=True`` (дефолт ``StateProxy.subscribe``) — здесь есть настоящий сервер
(``StateStoreManager`` на ``ProcessManager``), поэтому подписка блокируется до
подтверждения sub_id, а не остаётся локальной, как в изолированном тесте
``test_generic_process_state_proxy_acceptance.py``.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)


@register_plugin(
    "belt_reader", category="utility", description="Фикстура Task 2.0: подписан на sim.belt.* и читает его"
)
class BeltReaderPlugin(ProcessModulePlugin):
    """Подписан на ``sim.belt.*``, копит дельты, отдаёт снимок по команде."""

    name = "belt_reader"
    category = "utility"
    inputs: list = []
    outputs: list = []

    commands = {"received": "cmd_received", "get_belt": "cmd_get_belt"}

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._received: list[dict] = []
        if ctx.state_proxy is not None:
            ctx.state_proxy.subscribe("sim.belt.*", self._on_delta)

    def _on_delta(self, deltas: Any) -> None:
        for d in deltas:
            self._received.append({"path": d.path, "value": d.new_value})

    def cmd_received(self, _data: dict) -> dict:
        """Снимок накопленных дельт (тест опрашивает до появления записи)."""
        return {"status": "ok", "deltas": list(self._received)}

    def cmd_get_belt(self, _data: dict) -> dict:
        """Прямое чтение ``sim.belt.encoder`` через ``ctx.state_proxy.get``."""
        if self._ctx.state_proxy is None:
            return {"status": "error", "reason": "ctx.state_proxy is None"}
        value = self._ctx.state_proxy.get("sim.belt.encoder", None)
        return {"status": "ok", "value": value}

    def shutdown(self, ctx: PluginContext) -> None:
        pass
