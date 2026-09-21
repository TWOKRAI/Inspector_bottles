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

import threading
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
        self._reader: threading.Thread | None = None
        self._last_get: dict = {"status": "ok", "value": None}
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
        # Команда исполняется на приёмном потоке роутера. Синхронный get() там —
        # нарушение контракта реентерабельности (RouterReentrantRequestError,
        # state_proxy.py:1506): кэш хранит dict-значение листьями, поэтому
        # get("sim.belt.encoder") всегда уходит в IPC-фолбэк. Ждать фоновый поток
        # здесь тоже нельзя: ответ на его запрос разбирает этот же приёмный поток
        # (join = взаимная блокировка до таймаута). Поэтому команда не блокируется:
        # запускает чтение в фоне (если оно не идёт) и отдаёт последнее прочитанное;
        # тест опрашивает get_belt в цикле до дедлайна.
        if self._reader is None or not self._reader.is_alive():
            proxy = self._ctx.state_proxy

            def _read() -> None:
                try:
                    self._last_get = {"status": "ok", "value": proxy.get("sim.belt.encoder", None)}
                except Exception as exc:  # noqa: BLE001 — причина уходит в ответ команды
                    self._last_get = {"status": "error", "reason": repr(exc)}

            self._reader = threading.Thread(target=_read, name="belt_reader_get", daemon=True)
            self._reader.start()
        return dict(self._last_get)

    def shutdown(self, ctx: PluginContext) -> None:
        pass
