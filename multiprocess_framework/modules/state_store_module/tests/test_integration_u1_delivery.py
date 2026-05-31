"""Integration: реальный U1-путь доставки StateStore-телеметрии (без GUI).

Проверяет ПОЛНЫЙ контур БЕЗ GUI-окна и БЕЗ InMemoryRouter:

    StateStoreManager.handle_state_set         (как ProcessMonitor._publish_state)
      → DeltaDispatcher (match подписки)
      → RouterManager.send_async → _do_send → _resolve_channels()=[] (route нет)
      → _deliver_by_targets (U1) → queue_registry.send_to_queue(subscriber, "system", msg)
      → сообщение РЕАЛЬНО оказывается в очереди подписчика.

Закрывает баг, из-за которого cross-process подписка StateStore не работала в проде
(state.changed терялся в _resolve_channels; зелёными были только тесты через InMemoryRouter,
минующий каналы). Здесь RouterManager + StateStoreManager + DeltaDispatcher — настоящие.
"""

from __future__ import annotations

import queue as _queue

import pytest

from ...router_module.core.router_manager import RouterManager
from ..manager.state_store_manager import StateStoreManager


class _RealQueueRegistry:
    """Достоверный двойник «адресной книги» оркестратора.

    Контракт send_to_queue(process, qtype, msg) идентичен реальному QueueRegistry;
    очереди — настоящие queue.Queue, доступные подписчику для чтения. Этого достаточно,
    чтобы доказать сквозной путь: RouterManager._deliver_by_targets реально доставляет
    в очередь нужного процесса/типа.
    """

    def __init__(self) -> None:
        self._queues: dict[tuple[str, str], _queue.Queue] = {}

    def _q(self, process: str, qtype: str) -> _queue.Queue:
        return self._queues.setdefault((process, qtype), _queue.Queue())

    def register(self, process: str, qtypes: tuple[str, ...] = ("system", "data")) -> None:
        for qt in qtypes:
            self._q(process, qt)

    def send_to_queue(self, process: str, qtype: str, msg) -> bool:
        self._q(process, qtype).put(msg)
        return True

    def get(self, process: str, qtype: str, timeout: float = 2.0):
        return self._q(process, qtype).get(timeout=timeout)


def _make_server() -> tuple[StateStoreManager, RouterManager, _RealQueueRegistry]:
    qr = _RealQueueRegistry()
    qr.register("ProcessManager")
    qr.register("gui")
    router = RouterManager(manager_name="ProcessManager", queue_registry=qr)
    router.initialize()
    ssm = StateStoreManager(router=router, initial_state={}, logger=None)
    ssm.initialize()
    return ssm, router, qr


def test_published_state_delivered_to_subscriber_system_queue() -> None:
    """Публикация (как ProcessMonitor) → state.changed РЕАЛЬНО в gui_system-очереди."""
    ssm, router, qr = _make_server()
    try:
        # GUI подписывается (зеркало GuiStateProxy.subscribe, exclude_self=True)
        resp = ssm.handle_state_subscribe(
            {"data": {"pattern": "processes.**", "subscriber": "gui", "exclude_sources": ["gui"]}}
        )
        assert resp.get("status") == "ok"

        # ProcessMonitor публикует телеметрию воркера (локально, без IPC)
        ssm.handle_state_set(
            {
                "data": {
                    "path": "processes.cam0.workers.w1.effective_hz",
                    "value": 12.5,
                    "source": "ProcessMonitor",
                }
            }
        )

        # Сообщение должно реально оказаться в SYSTEM-очереди подписчика 'gui'
        msg = qr.get("gui", "system", timeout=2.0)
        assert msg["command"] == "state.changed"
        assert msg["queue_type"] == "system"
        assert msg["targets"] == ["gui"]
        deltas = msg["data"]["deltas"]
        assert deltas[0]["path"] == "processes.cam0.workers.w1.effective_hz"
        assert deltas[0]["new_value"] == 12.5
    finally:
        router.shutdown()


def test_process_status_change_delivered() -> None:
    """processes.X.state.status (как _broadcast_status_change) доходит до подписчика."""
    ssm, router, qr = _make_server()
    try:
        ssm.handle_state_subscribe(
            {"data": {"pattern": "processes.**", "subscriber": "gui", "exclude_sources": ["gui"]}}
        )
        ssm.handle_state_set(
            {"data": {"path": "processes.cam0.state.status", "value": "running", "source": "ProcessMonitor"}}
        )
        msg = qr.get("gui", "system", timeout=2.0)
        assert msg["data"]["deltas"][0]["path"] == "processes.cam0.state.status"
        assert msg["data"]["deltas"][0]["new_value"] == "running"
    finally:
        router.shutdown()


def test_path_outside_subscription_not_delivered() -> None:
    """Дельта вне паттерна подписки не доставляется (нет ложной доставки)."""
    ssm, router, qr = _make_server()
    try:
        ssm.handle_state_subscribe(
            {"data": {"pattern": "processes.**", "subscriber": "gui", "exclude_sources": ["gui"]}}
        )
        # Путь вне "processes.**"
        ssm.handle_state_set({"data": {"path": "system.health.active", "value": 3, "source": "pm"}})
        with pytest.raises(_queue.Empty):
            qr.get("gui", "system", timeout=0.5)
    finally:
        router.shutdown()
