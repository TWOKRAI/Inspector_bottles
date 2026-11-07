"""Тесты автора T5.3e.5b (C-60.b): хук ``DeviceHubPlugin.request_stop(ctx)`` и ``DeviceManager.request_stop_all_begin``.

Purpose:
    Свойства хука процесса, которые слепая приёмка (``test_c60b_hook_acceptance.py``) проверяет снаружи: хук не ждёт
    потоков стопа и замка воркеров, срок стопа считается от момента хука, супервизор защёлкнут, ``shutdown`` после
    хука делает всё прежнее и не даёт роботу второго стопа, подача на исполнитель процесса пуста. Хук зовётся прямо
    (фильтр состояний — забота фреймворка); супервизор — руками (``_process_conn_queue``, ``_ensure_device_workers``).

Public API:
    Только тесты ``test_*``.

Stability: lite

Обвязка: ``StopDriver`` (наследник ``FakeDriver``) пишет стоп-запрос (момент, срок, поток); повтор того же срока —
без записи, как у настоящего драйвера. Каждый вызов, который может зависнуть, идёт в
daemon-потоке с ``join``-дедлайном.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from multiprocess_framework.modules.base_manager.interfaces import ScopeClosedError
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Plugins.hub.device_hub.tests.test_spi_commands_acceptance import FakeDriver
from Services.device_hub.registry.entry import DeviceEntry

pytestmark = pytest.mark.timeout(60)

_JOIN_S = 2.0  # любой вызов, который может зависнуть, не ждётся дольше
_HOOK_BUDGET_S = 0.2  # хук возвращается не позже
_HOLD_S = 30.0  # потолок ожидания висящего стопа (тест снимает зависание сам)
_ECHO_CONTEXT = "device_hub.stop_echo"


class StopDriver(FakeDriver):
    """Подключённый робот с ``stop_aware``: пишет стоп-запрос и ждёт ``release`` (если ``hold``).

    Повтор с тем же сроком стопа не даёт (как настоящий драйвер: защёлка по сроку) — на текущем коде менеджер зовёт
    ``request_stop`` дважды с одним сроком за один ``shutdown`` (``shutdown`` плагина, затем ``_on_shutdown``).
    """

    kind = "robot"
    stop_aware = True

    def __init__(self, entry: Any, *, release: threading.Event, hold: float = 0.0, up: bool = True) -> None:
        super().__init__(entry)
        self.up = up
        self.release = release
        self.hold = hold  # 0 — мгновенно; > 0 — столько секунд; _HOLD_S — до release
        self.calls_stop: list[tuple[float, float, int]] = []  # (момент входа, срок, ident потока)
        self.raw_calls = 0  # все вызовы request_stop, до дедупликации по сроку
        self._seen: set[float] = set()
        self.entered = threading.Event()
        self.finished_at: float | None = None
        self.connect_calls = 0
        self.unconfirmed_text: str | None = None

    def connect(self) -> bool:
        self.connect_calls += 1
        self.up = True
        return True

    def request_stop(self, deadline: float) -> None:
        self.raw_calls += 1
        if deadline in self._seen:
            return
        self._seen.add(deadline)
        self.calls_stop.append((time.monotonic(), deadline, threading.get_ident()))
        self.entered.set()
        if self.unconfirmed_text is not None:
            self.stop_unconfirmed = True
            self.stop_unconfirmed_text = self.unconfirmed_text
        if self.hold:
            self.release.wait(self.hold)
        self.finished_at = time.monotonic()


@dataclass
class Hub:
    plugin: DeviceHubPlugin
    ctx: MagicMock
    release: threading.Event = field(default_factory=threading.Event)
    drivers: dict[str, StopDriver] = field(default_factory=dict)

    def add(self, dev_id: str, *, up: bool = True, workers: bool = True, **kw: Any) -> StopDriver:
        """Запись в реестре + поддельный драйвер в менеджере (+ воркер ``dev_<id>`` подключённому)."""
        transport = {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2}
        res = self.plugin.cmd_device_upsert({"id": dev_id, "name": dev_id, "kind": "robot", "transport": transport})
        assert res["status"] == "ok", res
        driver = StopDriver(
            DeviceEntry(id=dev_id, name=dev_id, kind="robot", transport=transport), release=self.release, up=up, **kw
        )
        if up and workers:
            with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
                self.plugin.cmd_device_connect({"device_id": dev_id})
                self.plugin._process_conn_queue()
        self.plugin._manager._drivers[dev_id] = driver
        self.drivers[dev_id] = driver
        if up and workers:
            driver.desired_connected = True
            self.plugin._ensure_device_workers()
        return driver

    def hook(self) -> tuple[float, float, int]:
        """Хук в daemon-потоке: (момент входа, длительность, ident потока хука)."""
        return call_hook(self.plugin, self.ctx)

    def shutdown(self) -> float:
        """``plugin.shutdown`` в daemon-потоке; возвращает ``monotonic()`` возврата."""
        return bounded(lambda: (self.plugin.shutdown(self.ctx), time.monotonic())[1], 15.0)

    def connect_cmd(self, dev_id: str) -> None:
        """Команда «Подключить» + проход супервизора (как в ``_connect_command`` приёмки)."""
        self.plugin.cmd_device_connect({"device_id": dev_id})
        self.plugin._process_conn_queue()


def bounded(fn: Callable[[], Any], join_s: float) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносится в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name="c60b-author")
    thread.start()
    thread.join(join_s)
    assert not thread.is_alive(), f"вызов завис дольше {join_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def call_hook(plugin: DeviceHubPlugin, ctx: Any) -> tuple[float, float, int]:
    def body() -> tuple[float, float, int]:
        t0 = time.monotonic()
        plugin.request_stop(ctx)
        return t0, time.monotonic() - t0, threading.get_ident()

    return bounded(body, _JOIN_S)


@pytest.fixture
def make_hub(tmp_path: Path) -> Iterator[Callable[[], Hub]]:
    made: list[Hub] = []

    def factory() -> Hub:
        registry = tmp_path / f"devices{len(made)}.yaml"
        ctx = make_ctx({"registry_path": str(registry)}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        ctx.command_manager.reset_mock()  # configure/start оставили вызовы регистрации
        made.append(Hub(plugin=plugin, ctx=ctx))
        return made[-1]

    yield factory
    for hub in made:
        hub.release.set()  # отпустить висящие стопы, затем закрыть
        try:
            bounded(lambda h=hub: h.plugin.shutdown(h.ctx), 15.0)
        except BaseException:  # noqa: BLE001 — уборка не подменяет провал теста
            pass


@pytest.fixture
def hub(make_hub: Callable[[], Hub]) -> Hub:
    return make_hub()


def test_hook_returns_without_waiting_stop_threads(hub: Hub) -> None:
    r1 = hub.add("r1", hold=_HOLD_S)
    _t0, elapsed, hook_thread = hub.hook()
    assert elapsed <= _HOOK_BUDGET_S, f"хук занял {elapsed:.3f} с при висящем стопе робота"
    assert r1.entered.wait(1.0), "стоп не дошёл до робота"
    assert len(r1.calls_stop) == 1
    assert r1.calls_stop[0][2] != hook_thread, "стоп робота исполнен на потоке хука"


def test_hook_does_not_wait_workers_lock(hub: Hub) -> None:
    hub.add("r1")
    r2 = hub.add("r2", up=False)
    held, let_go = threading.Event(), threading.Event()

    def holder() -> None:
        with hub.plugin._workers_lock:
            held.set()
            let_go.wait(15.0)

    thread = threading.Thread(target=holder, daemon=True, name="c60b-lock-holder")
    thread.start()
    try:
        assert held.wait(2.0)
        _t0, elapsed, _ = hub.hook()
        assert elapsed <= _HOOK_BUDGET_S, f"хук ждал замок воркеров: {elapsed:.3f} с"
    finally:
        let_go.set()
        thread.join(2.0)
    bounded(lambda: hub.connect_cmd("r2"), _JOIN_S)
    assert r2.connect_calls == 0, "хук не защёлкнул супервизор, пока замок держал другой поток"


def test_hook_deadline_counted_from_hook(hub: Hub) -> None:
    r1 = hub.add("r1")
    t0, _elapsed, _ = hub.hook()
    assert r1.entered.wait(1.0)
    time.sleep(0.5)
    hub.shutdown()
    assert len(r1.calls_stop) == 1
    assert 2.4 <= r1.calls_stop[0][1] - t0 <= 2.6, r1.calls_stop[0][1] - t0


def test_hook_latches_supervisor(hub: Hub) -> None:
    hub.add("r1")
    r2 = hub.add("r2", up=False)
    hub.hook()
    bounded(lambda: hub.connect_cmd("r2"), _JOIN_S)
    assert r2.connect_calls == 0


def test_shutdown_after_hook_keeps_phase_steps(hub: Hub) -> None:
    ctx = hub.ctx
    r1 = hub.add("r1")
    r1.unconfirmed_text = "стоп не подтверждён роботом"
    assert "dev_r1" in ctx.worker_manager.workers and "r1" in hub.plugin._device_workers  # без этого шаги пусты
    scope = hub.plugin._scope
    hub.hook()
    assert r1.entered.wait(1.0)
    late = hub.add("late", workers=False)  # появился после хука
    hub.shutdown()
    assert "dev_r1" not in ctx.worker_manager.workers
    with pytest.raises(ScopeClosedError):
        scope.spawn(lambda *_: None, name="x")
    assert r1.disconnect_calls >= 1
    echo = [c for c in ctx.health.report_error.call_args_list if c.kwargs.get("context") == _ECHO_CONTEXT]
    assert [(str(c.args[0]), c.kwargs.get("device_id")) for c in echo] == [("стоп не подтверждён роботом", "r1")]
    assert len(r1.calls_stop) == 1, "бывший до хука робот получил не один стоп"
    assert len(late.calls_stop) == 1, "появившийся после хука робот получил не один стоп"


def test_shutdown_waits_hook_threads(hub: Hub) -> None:
    r1 = hub.add("r1", hold=0.5)
    hub.hook()
    assert r1.entered.wait(1.0)
    assert r1.finished_at is None
    hub.shutdown()
    assert r1.finished_at is not None, "shutdown вернулся раньше конца стопа из хука"


def test_hook_twice_and_parallel_requests_once(make_hub: Callable[[], Hub]) -> None:
    seq = make_hub()
    r1 = seq.add("r1")
    seq.hook()
    seq.hook()
    assert r1.entered.wait(1.0), "стоп из хука не дошёл до робота"
    seq.shutdown()
    assert len(r1.calls_stop) == 1, "два хука подряд дали повторный стоп"

    par = make_hub()
    r2 = par.add("r2")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def body() -> None:
        try:
            barrier.wait(5.0)
            par.plugin.request_stop(par.ctx)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=body, daemon=True, name=f"c60b-par-{i}") for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_JOIN_S)
    assert not any(t.is_alive() for t in threads) and errors == [], errors
    assert r2.entered.wait(1.0), "стоп из хука не дошёл до робота"
    par.shutdown()
    assert len(r2.calls_stop) == 1, "два хука из разных потоков дали повторный стоп"


def test_hook_direct_after_shutdown_and_unconfigured_is_noop(hub: Hub) -> None:
    r1 = hub.add("r1")
    hub.shutdown()
    assert len(r1.calls_stop) == 1
    hub.hook()  # scope уже None
    assert len(r1.calls_stop) == 1
    call_hook(DeviceHubPlugin(), make_ctx())  # без configure — без исключения


def test_shutdown_without_hook_latches_supervisor(hub: Hub) -> None:
    r1 = hub.add("r1", hold=_HOLD_S)
    r2 = hub.add("r2", up=False)
    outcome: dict[str, Any] = {}
    shutdown_thread = threading.Thread(
        target=lambda: outcome.update(t=hub.plugin.shutdown(hub.ctx)), daemon=True, name="c60b-shutdown"
    )
    shutdown_thread.start()
    try:
        assert r1.entered.wait(2.0), "shutdown без хука не дошёл до стопа"
        bounded(lambda: hub.connect_cmd("r2"), _JOIN_S)  # shutdown ещё идёт: стоп робота висит
        assert shutdown_thread.is_alive(), "обвязка: shutdown успел закончиться"
    finally:
        hub.release.set()
        shutdown_thread.join(15.0)
    assert r2.connect_calls == 0, "«Подключить» во время shutdown подключила устройство"
    assert len(r1.calls_stop) == 1


def test_hook_puts_nothing_on_executor(hub: Hub) -> None:
    r1 = hub.add("r1")
    hub.ctx.command_manager.reset_mock()
    _t0, _elapsed, hook_thread = hub.hook()
    assert r1.entered.wait(1.0)
    time.sleep(0.2)  # подача могла бы прийти с потока стопа уже после возврата хука
    assert hub.ctx.command_manager.mock_calls == [], hub.ctx.command_manager.mock_calls
    assert r1.calls_stop[0][2] != hook_thread


def test_late_robot_not_delayed_by_hung_neighbour(hub: Hub) -> None:
    r1 = hub.add("r1", hold=_HOLD_S)  # висит, пока тест не отпустит
    hub.hook()
    assert r1.entered.wait(1.0)
    late = hub.add("late", workers=False)  # появился после хука
    thread = threading.Thread(target=lambda: hub.plugin.shutdown(hub.ctx), daemon=True, name="c60b-shutdown")
    thread.start()
    try:
        delivered = late.entered.wait(1.0)
        assert r1.finished_at is None, "обвязка: зависший сосед уже отпущен"
        assert delivered, "позднему роботу стоп не ушёл за 1,0 с: запись ждёт зависшего соседа"
    finally:
        hub.release.set()
        thread.join(15.0)
    assert not thread.is_alive()


def test_new_driver_object_under_same_id_gets_one_stop(hub: Hub) -> None:
    old = hub.add("r1")
    hub.hook()
    assert old.entered.wait(1.0)
    transport = {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2}
    new = StopDriver(DeviceEntry(id="r1", name="r1", kind="robot", transport=transport), release=hub.release)
    hub.plugin._manager._drivers["r1"] = new  # remove + upsert того же id: новый объект под прежним id
    hub.shutdown()
    assert len(old.calls_stop) == 1
    assert len(new.calls_stop) == 1, "новый объект драйвера под прежним id остался без стопа"


def test_hook_then_shutdown_sends_one_raw_call_per_robot(hub: Hub) -> None:
    r1 = hub.add("r1")
    hub.hook()
    assert r1.entered.wait(1.0)
    late = hub.add("late", workers=False)
    hub.shutdown()  # фаза 1 (request_stop_all) и фаза 4 (_on_shutdown) с тем же сроком хука
    assert (r1.raw_calls, late.raw_calls) == (1, 1), "повторный вызов request_stop за закрытие (до дедупа по сроку)"
