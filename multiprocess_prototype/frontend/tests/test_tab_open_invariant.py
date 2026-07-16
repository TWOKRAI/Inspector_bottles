# -*- coding: utf-8 -*-
"""CI-инвариант плана gui-telemetry-read-model (Фаза 3, Task 3.1).

Закрепляет ПРИНЦИП плана на уровне интеграции ВСЕХ вкладок (не только
«Процессов»): открытие вкладки не делает блокирующий IPC в GUI main thread.

Инварианты (из раздела «Принцип»):
  1. GUI main thread НЕ делает блокирующий ``router.request`` при открытии
     вкладки — все подписки идут fire-and-forget (``subscribe(sync=False)``,
     Фаза 0 Task 0.2).
  2. Открытие вкладки не создаёт серверных ``state.subscribe`` для путей,
     ПОКРЫТЫХ стартовыми wildcard'ами (coverage-check, Фаза 0 Task 0.1).

Тест строит все 7 вкладок через ``register_all_tabs()`` (как
``test_phase10_integration.test_all_tabs_creatable``), но с РЕАЛЬНЫМ
``GuiStateBindings`` поверх ``GuiStateProxy`` со spy-router. Любой ``bind()``
вкладки при конструировании проходит штатный путь proxy → router, и spy ловит,
был ли он блокирующим.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.state_store_module.core import pattern_covers
from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import GuiStateProxy
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.state.telemetry_view_model import TelemetryViewModel
from multiprocess_prototype.frontend.widgets.tabs import register_all_tabs

# Стартовые wildcard'ы GUI (frontend/process.py) — заводятся sync=True и
# ПОДТВЕРЖДАЮТСЯ сервером до открытия любой вкладки.
_STARTUP_WILDCARDS = ("processes.**", "system.**", "devices.**", "calibration.**")


class _SyncBridge:
    """Синхронный дубль DataReceiverBridge для state-пути (как в test_bindings)."""

    def __init__(self) -> None:
        self._state_cb = None
        self._state_listeners: list = []

    def set_state_callback(self, cb) -> None:
        self._state_cb = cb

    def add_state_listener(self, cb) -> None:
        self._state_listeners.append(cb)

    def dispatch(self, msg_dict: dict) -> None:
        if self._state_cb is not None:
            self._state_cb(msg_dict)
        for cb in list(self._state_listeners):
            cb(msg_dict)


class _SpyRouter:
    """Router-шпион: считает блокирующие request и async state.subscribe."""

    def __init__(self) -> None:
        self.blocking_requests: list[dict] = []
        self.async_subscribes: list[dict] = []
        self._seq = 0

    def register_message_handler(self, *a, **k) -> None:
        pass

    def send_async(self, msg, priority: str = "normal") -> None:
        if isinstance(msg, dict) and msg.get("command") == "state.subscribe":
            self.async_subscribes.append(msg)

    def request(self, msg, timeout: float = 5.0) -> dict:
        # Блокирующий раундтрип — ровно то, чего на открытии вкладки быть НЕ должно.
        self.blocking_requests.append(msg)
        self._seq += 1
        return {"success": True, "result": {"status": "ok", "sub_id": f"srv-{self._seq}"}}

    def reset(self) -> None:
        self.blocking_requests.clear()
        self.async_subscribes.clear()


def _subscribe_pattern(msg: dict) -> str:
    return str(msg.get("data", {}).get("pattern", ""))


def _make_services() -> Any:
    from multiprocess_prototype.domain.tests.conftest import make_test_app_services

    return make_test_app_services()


def test_opening_all_tabs_does_no_blocking_ipc(qtbot) -> None:
    """Открытие каждой из 7 вкладок → 0 блокирующего router.request из main thread.

    Плюс: для путей, покрытых стартовыми wildcard'ами, 0 серверных state.subscribe
    (coverage-check). Непокрытые пути допустимо подписывать async (не блокирует).
    """
    router = _SpyRouter()
    bridge = _SyncBridge()
    proxy = GuiStateProxy("gui", router=router, delta_sink=lambda _deltas: None)

    # Стартовые wildcard'ы sync=True → ПОДТВЕРЖДЕНЫ (как в проде до открытия вкладок).
    for wildcard in _STARTUP_WILDCARDS:
        proxy.subscribe(wildcard, lambda _d: None, exclude_self=True)
    assert all(w in proxy._confirmed_patterns for w in _STARTUP_WILDCARDS)

    bindings = GuiStateBindings(
        bridge,
        ensure_subscription=proxy.ensure_subscription,
        release_subscription=proxy.release_subscription,
        cache_snapshot=lambda: dict(proxy.cache),
    )

    # Забываем стартовые (sync) request'ы — меряем только эффект открытия вкладок.
    router.reset()

    services = _make_services()
    runtime = RuntimeDeps(bindings=bindings, telemetry=TelemetryViewModel())

    factories = register_all_tabs()
    for tab_id, factory in factories.items():
        widget = factory(services, runtime)
        qtbot.addWidget(widget)
        assert widget is not None, f"Таб '{tab_id}' вернул None"

    # Инвариант 1: ни одного блокирующего router.request из main thread.
    assert router.blocking_requests == [], (
        f"блокирующий router.request на открытии вкладок: {[m.get('command') for m in router.blocking_requests]}"
    )

    # Инвариант 2: покрытый стартовым wildcard путь НЕ создаёт серверную подписку.
    covered = [
        m for m in router.async_subscribes if any(pattern_covers(w, _subscribe_pattern(m)) for w in _STARTUP_WILDCARDS)
    ]
    assert covered == [], (
        f"covered-путь создал серверную подписку (coverage-check пробит): {[_subscribe_pattern(m) for m in covered]}"
    )
