"""Слепая приёмка T5.3e.5b (C-60.b): стоп хаба устройств в хуке процесса ``DeviceHubPlugin.request_stop(ctx)``.

Purpose:
    Хук ``plugin.request_stop(ctx)`` (зовётся прямо, без фреймворка) раздаёт стоп-запрос роботам, не блокируя поток
    хука, а ``plugin.shutdown(ctx)`` после хука закрывает хаб как раньше и не шлёт роботу второй стоп. Источник
    истины — ``plans/robot-protocol-v2/tasks/T5.3e.5b.acceptance.md`` (раздел ACCEPTANCE 5b), не код плагина.
    Наблюдается только внешний эффект: сколько раз и когда вызван ``request_stop`` поддельного робота, на каком
    потоке, с каким сроком; какие воркеры остались; закрыта ли область потоков; что ушло в health и в журнал.

Public API:
    Только тесты ``test_*``.

Stability: lite

Обвязка (поддельный робот, ``make_ctx``):
    * ``StopRobot`` — наследник ``FakeDriver`` из слепой приёмки SPI: ``stop_aware = True``, ``request_stop(deadline)``
      пишет вызов (момент ``time.monotonic()``, срок, поток) и ведёт себя по режиму (мгновенно / ``slow`` / ``hang``),
      идемпотентен по сроку, как настоящий драйвер (повтор с тем же ``deadline`` стопа не даёт: менеджер на текущем
      коде зовёт ``request_stop`` дважды с одним сроком за один ``shutdown``) — «стоп-запрос» = первый вызов на срок,
      ``connect()`` считает подключения, ``stop_unconfirmed`` и ``stop_unconfirmed_text`` выставляются из
      ``request_stop``. Кладётся в менеджер ``plugin._manager._drivers[id]`` как в ``test_lifecycle_regressions.py``.
    * ``ctx`` — ``make_ctx``; ``ctx.command_manager`` — ``MagicMock`` (после ``start`` — ``reset_mock()``).
    * Блокирующие вызовы (хук, ``shutdown``) идут в daemon-потоке с ``join(дедлайн)``.

Допущения (не следуют из приёмки буквально, см. отчёт):
    * Срок, который хаб передаёт в ``request_stop(deadline)``, — на часах ``time.monotonic()``.
    * Срок «хук + 2,5 с» меряется от момента ВХОДА в хук (``t_before``) до момента возврата (``t_after``), с допуском
      ±0,1 с в обе стороны.
    * Таймерные пороги (0,2 с; ±0,1 с) чувствительны к нагрузке машины: под тяжёлой нагрузкой возможны ложные красные.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
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

# --------------------------------------------------------------------------------------------------
# Литералы приёмки
# --------------------------------------------------------------------------------------------------

_HOOK_BUDGET_S = 0.2  # хук возвращается не позже
_STOP_BUDGET_S = 2.5  # срок стоп-запроса = момент хука + 2,5 с
_STOP_TOLERANCE_S = 0.1  # допуск срока
_ONE = 1
_HOOK_LOG = "DeviceHubPlugin: request_stop"
_STOP_ECHO_CONTEXT = "device_hub.stop_echo"

_CALL_DEADLINE_S = 15.0  # зависший вызов хука / shutdown не вешает набор
_DELIVERY_S = 1.0  # стоп из хука должен дойти до робота за это время
_SETTLE_S = 0.3  # запоздалый дубль стопа считается: ждём после возврата
_SLOW_STOP_S = 0.6  # режим slow: стоп робота идёт столько секунд
_HANG_RELEASE_S = 30.0  # потолок ожидания висящего стопа (тест всегда снимает зависание сам)
_PAST_DEADLINE_S = 0.5  # shutdown после срока: запас сверху


# --------------------------------------------------------------------------------------------------
# Поддельный робот с остановкой
# --------------------------------------------------------------------------------------------------


@dataclass
class StopCall:
    """Один вызов ``request_stop`` поддельного робота."""

    at: float  # time.monotonic() входа
    deadline: float  # переданный срок
    thread: int  # threading.get_ident() потока, где исполнился вызов
    done_at: float | None = None  # time.monotonic() выхода; None — вызов ещё идёт (или завис)


class StopRobot(FakeDriver):
    """Подключённый (``up=True``) робот с ``stop_aware``; считает стопы и подключения."""

    kind = "robot"
    stop_aware = True

    def __init__(
        self,
        entry: Any,
        protocol: Any = None,
        *,
        up: bool = True,
        mode: str = "instant",
        release: threading.Event | None = None,
        unconfirmed_text: str | None = None,
    ) -> None:
        super().__init__(entry, protocol)
        self.up = up
        self.mode = mode  # "instant" | "slow" | "hang"
        self.release = release or threading.Event()
        self.unconfirmed_text = unconfirmed_text
        self.stops: list[StopCall] = []  # действенные стоп-запросы: первый вызов на каждый срок
        self.raw_calls = 0  # все вызовы request_stop, с повторами того же срока
        self._seen_deadlines: set[float] = set()
        self.entered = threading.Event()
        self.connect_calls = 0
        self._guard = threading.Lock()

    def connect(self) -> bool:
        with self._guard:
            self.connect_calls += 1
        self.up = True
        return True

    def request_stop(self, deadline: float) -> None:
        rec = StopCall(at=time.monotonic(), deadline=deadline, thread=threading.get_ident())
        with self._guard:
            self.raw_calls += 1
            if deadline in self._seen_deadlines:
                return  # повтор того же срока: как у настоящего драйвера, стопа не даёт
            self._seen_deadlines.add(deadline)
            self.stops.append(rec)
        self.entered.set()
        if self.unconfirmed_text is not None:
            self.stop_unconfirmed = True
            self.stop_unconfirmed_text = self.unconfirmed_text
        if self.mode == "slow":
            time.sleep(_SLOW_STOP_S)
        elif self.mode == "hang":
            self.release.wait(_HANG_RELEASE_S)
        rec.done_at = time.monotonic()

    def stop_count(self) -> int:
        with self._guard:
            return len(self.stops)


# --------------------------------------------------------------------------------------------------
# Стенд хаба
# --------------------------------------------------------------------------------------------------


@dataclass
class HookRun:
    """Итог вызова ``plugin.request_stop(ctx)`` в отдельном потоке."""

    elapsed: float
    t_before: float  # time.monotonic() перед вызовом (в потоке хука)
    t_after: float  # time.monotonic() после возврата
    thread: int  # ident потока хука


@dataclass
class Hub:
    """Настоящий ``DeviceHubPlugin`` на ``make_ctx`` (после ``configure`` + ``start``)."""

    plugin: DeviceHubPlugin
    ctx: MagicMock
    release: threading.Event = field(default_factory=threading.Event)
    robots: dict[str, StopRobot] = field(default_factory=dict)
    scope: Any = None

    def add_robot(self, dev_id: str, *, up: bool = True, workers: bool = True, **kw: Any) -> StopRobot:
        """Устройство в реестре + поддельный драйвер в менеджере (+ воркер ``dev_<id>`` для подключённого)."""
        transport = {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2}
        res = self.plugin.cmd_device_upsert({"id": dev_id, "name": dev_id, "kind": "robot", "transport": transport})
        assert res["status"] == "ok", res
        entry = DeviceEntry(id=dev_id, name=dev_id, kind="robot", transport=transport)
        robot = StopRobot(entry, up=up, release=self.release, **kw)
        if up and workers:
            # как в test_lifecycle_regressions: «Подключить» ставит желаемое состояние (connect менеджера подменён),
            # затем в менеджер кладётся поддельный драйвер и создаётся воркер устройства
            with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
                self.plugin.cmd_device_connect({"device_id": dev_id})
                self.plugin._process_conn_queue()
        self.plugin._manager._drivers[dev_id] = robot
        self.robots[dev_id] = robot
        if up and workers:
            robot.desired_connected = True
            self.plugin._ensure_device_workers()
            assert f"dev_{dev_id}" in self.ctx.worker_manager.workers, "обвязка: воркер устройства не создан"
        return robot

    def hook(self, deadline_s: float = _CALL_DEADLINE_S) -> HookRun:
        return run_hook(self.plugin, self.ctx, deadline_s)

    def shutdown(self, deadline_s: float = _CALL_DEADLINE_S) -> float:
        """``plugin.shutdown(ctx)`` в daemon-потоке с дедлайном; возвращает ``time.monotonic()`` возврата."""
        box = bounded(lambda: (self.plugin.shutdown(self.ctx), time.monotonic())[1], deadline_s)
        return box

    def close(self) -> None:
        self.release.set()  # отпустить висящие стопы, потом закрыть
        try:
            bounded(lambda: self.plugin.shutdown(self.ctx), _CALL_DEADLINE_S)
        except BaseException:  # noqa: BLE001 — уборка не подменяет провал теста
            pass


def bounded(fn: Callable[[], Any], deadline_s: float) -> Any:
    """Вызов в daemon-потоке с join-дедлайном; ошибка потока поднимается в тесте, зависание — ``AssertionError``."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносится в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name="c60b-bounded")
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def run_hook(plugin: DeviceHubPlugin, ctx: Any, deadline_s: float = _CALL_DEADLINE_S) -> HookRun:
    """Хук ``plugin.request_stop(ctx)`` в daemon-потоке; исключение хука поднимается в потоке теста."""
    box: dict[str, Any] = {}

    def body() -> None:
        box["thread"] = threading.get_ident()
        box["t0"] = time.monotonic()
        try:
            plugin.request_stop(ctx)  # type: ignore[attr-defined]
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        box["t1"] = time.monotonic()

    thread = threading.Thread(target=body, daemon=True, name="c60b-hook")
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"хук не вернулся за {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return HookRun(elapsed=box["t1"] - box["t0"], t_before=box["t0"], t_after=box["t1"], thread=box["thread"])


def wait_entered(robot: StopRobot, what: str = "") -> None:
    assert robot.entered.wait(_DELIVERY_S), f"{what}стоп не дошёл до робота за {_DELIVERY_S} с"


@pytest.fixture
def hub(tmp_path: Path):
    registry = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry)}, tmp_registry=registry)
    ctx.health = MagicMock()
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    ctx.command_manager.reset_mock()  # configure/start оставили вызовы регистрации
    made = Hub(plugin=plugin, ctx=ctx, scope=plugin._scope)
    yield made
    made.close()


# --------------------------------------------------------------------------------------------------
# 1. Хук возвращается <= 0,2 с
# --------------------------------------------------------------------------------------------------


def test_hook_returns_within_budget_when_robot_stop_hangs(hub: Hub) -> None:
    r1 = hub.add_robot("r1", mode="hang")
    run = hub.hook()
    assert run.elapsed <= _HOOK_BUDGET_S, f"хук занял {run.elapsed:.3f} с при висящем стопе робота (> 0,2)"
    wait_entered(r1, "быстрый возврат не должен быть пустым хуком: ")


def test_hook_returns_within_budget_when_workers_lock_held_by_other_thread(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    held = threading.Event()
    let_go = threading.Event()

    def holder() -> None:
        with hub.plugin._workers_lock:
            held.set()
            let_go.wait(_CALL_DEADLINE_S)

    thread = threading.Thread(target=holder, daemon=True, name="c60b-lock-holder")
    thread.start()
    try:
        assert held.wait(2.0), "обвязка: поток не взял замок воркеров"
        run = hub.hook(deadline_s=5.0)
        assert run.elapsed <= _HOOK_BUDGET_S, f"хук занял {run.elapsed:.3f} с, пока замок воркеров держит другой поток"
    finally:
        let_go.set()
        thread.join(2.0)
    wait_entered(r1, "после снятия замка воркеров: ")  # быстрый возврат не должен быть пустым хуком


# --------------------------------------------------------------------------------------------------
# 2. Стоп не на потоке хука; 0 подач на исполнитель
# --------------------------------------------------------------------------------------------------


def test_robot_stop_from_hook_runs_on_other_thread_than_hook(hub: Hub) -> None:
    r1 = hub.add_robot("r1", mode="hang")
    run = hub.hook()
    wait_entered(r1)
    assert r1.stops[0].thread != run.thread, "стоп робота исполнен на потоке хука"


def test_hook_submits_no_operations_to_process_executor(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    assert hub.ctx.command_manager.mock_calls == [], "обвязка: после reset_mock в command_manager остались вызовы"
    hub.hook()
    wait_entered(r1)
    time.sleep(_SETTLE_S)  # подача могла бы прийти с потока стопа уже после возврата хука
    assert hub.ctx.command_manager.mock_calls == [], hub.ctx.command_manager.mock_calls


# --------------------------------------------------------------------------------------------------
# 3. Ровно 1 стоп-запрос за закрытие
# --------------------------------------------------------------------------------------------------


def test_exactly_one_stop_hook_then_shutdown(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    hub.hook()
    wait_entered(r1, "хук: ")  # стоп уходит из хука, не откладывается до shutdown
    hub.shutdown()
    time.sleep(_SETTLE_S)
    assert r1.stop_count() == _ONE, f"стопов за закрытие (хук -> shutdown): {r1.stop_count()}"


def test_exactly_one_stop_two_hooks_in_a_row(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    hub.hook()
    hub.hook()
    wait_entered(r1, "хук: ")
    hub.shutdown()
    time.sleep(_SETTLE_S)
    assert r1.stop_count() == _ONE, f"стопов за закрытие (два хука подряд, затем shutdown): {r1.stop_count()}"


def test_exactly_one_stop_two_hooks_in_a_row_before_shutdown_even_if_stop_hangs(hub: Hub) -> None:
    r1 = hub.add_robot("r1", mode="hang")
    hub.hook()
    wait_entered(r1)
    hub.hook()
    time.sleep(_SETTLE_S)
    assert r1.stop_count() == _ONE, f"стопов после двух хуков подряд при висящем стопе: {r1.stop_count()}"


def test_exactly_one_stop_two_hooks_from_different_threads_at_once(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def body() -> None:
        try:
            barrier.wait(5.0)
            hub.plugin.request_stop(hub.ctx)  # type: ignore[attr-defined]
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=body, daemon=True, name=f"c60b-hook-{i}") for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(_CALL_DEADLINE_S)
    assert not any(t.is_alive() for t in threads), "хук завис"
    assert errors == [], errors
    wait_entered(r1, "хуки: ")
    hub.shutdown()
    time.sleep(_SETTLE_S)
    assert r1.stop_count() == _ONE, f"стопов за закрытие (два хука из разных потоков одновременно): {r1.stop_count()}"


def test_exactly_one_stop_shutdown_without_hook(hub: Hub) -> None:
    # Контроль обвязки: на текущем коде зелёный (стоп при shutdown без хука — как раньше).
    r1 = hub.add_robot("r1")
    hub.shutdown()
    time.sleep(_SETTLE_S)
    assert r1.stop_count() == _ONE, f"стопов за закрытие (shutdown без хука): {r1.stop_count()}"


# --------------------------------------------------------------------------------------------------
# 4. Срок стоп-запроса = момент хука + 2,5 с (±0,1 с)
# --------------------------------------------------------------------------------------------------


def test_stop_deadline_is_hook_moment_plus_budget(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    run = hub.hook()
    wait_entered(r1)
    deadline = r1.stops[0].deadline
    low = run.t_before + _STOP_BUDGET_S - _STOP_TOLERANCE_S
    high = run.t_after + _STOP_BUDGET_S + _STOP_TOLERANCE_S
    assert low <= deadline <= high, (
        f"срок {deadline - run.t_before:.3f} с от входа в хук (ждали 2,5 +- 0,1; хук шёл {run.elapsed:.3f} с)"
    )


def test_stop_deadline_is_not_shifted_to_shutdown_moment(hub: Hub) -> None:
    # Между хуком и shutdown проходит 1,0 с: срок остаётся «хук + 2,5», а не «shutdown + 2,5».
    r1 = hub.add_robot("r1")
    run = hub.hook()
    time.sleep(1.0)
    t_shutdown = time.monotonic()
    hub.shutdown()
    assert r1.stop_count() == _ONE, f"стопов: {r1.stop_count()}"
    deadline = r1.stops[0].deadline
    assert abs(deadline - (run.t_before + _STOP_BUDGET_S)) <= _STOP_TOLERANCE_S + run.elapsed, (
        f"срок {deadline - run.t_before:.3f} с от хука; от shutdown {deadline - t_shutdown:.3f} с (ждали 2,5 от хука)"
    )


# --------------------------------------------------------------------------------------------------
# 5. «Подключить» не подключает после хука и во время shutdown
# --------------------------------------------------------------------------------------------------


def _connect_command(hub: Hub, dev_id: str) -> None:
    hub.plugin.cmd_device_connect({"device_id": dev_id})
    bounded(hub.plugin._process_conn_queue, _CALL_DEADLINE_S)


def test_connect_without_hook_connects_device(hub: Hub) -> None:
    # Контроль обвязки: на текущем коде зелёный — иначе тесты «не подключает» были бы пусты.
    r2 = hub.add_robot("r2", up=False)
    _connect_command(hub, "r2")
    assert r2.connect_calls == _ONE, f"обвязка: «Подключить» без хука дал {r2.connect_calls} подключений"


def test_connect_after_hook_does_not_connect_device(hub: Hub) -> None:
    hub.add_robot("r1")
    r2 = hub.add_robot("r2", up=False)
    hub.hook()
    _connect_command(hub, "r2")
    assert r2.connect_calls == 0, f"«Подключить» после хука подключил устройство ({r2.connect_calls} раз)"
    assert r2.is_connected is False


def test_connect_during_shutdown_without_hook_does_not_connect_device(hub: Hub) -> None:
    r1 = hub.add_robot("r1", mode="hang")
    r2 = hub.add_robot("r2", up=False)
    outcome: dict[str, Any] = {}

    def do_shutdown() -> None:
        try:
            hub.plugin.shutdown(hub.ctx)
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc

    def do_connect() -> None:
        try:
            _connect_command(hub, "r2")
        except BaseException as exc:  # noqa: BLE001
            outcome["connect_error"] = exc

    shutdown_thread = threading.Thread(target=do_shutdown, daemon=True, name="c60b-shutdown")
    connect_thread = threading.Thread(target=do_connect, daemon=True, name="c60b-connect")
    try:
        shutdown_thread.start()
        wait_entered(r1, "shutdown без хука: ")  # shutdown сидит в фазе стопа, стоп робота висит
        connect_thread.start()
        connect_thread.join(0.5)
    finally:
        hub.release.set()  # отпустить висящий стоп: shutdown закончится
        shutdown_thread.join(_CALL_DEADLINE_S)
        connect_thread.join(_CALL_DEADLINE_S)
    assert not shutdown_thread.is_alive() and not connect_thread.is_alive(), "shutdown или подключение зависли"
    assert "error" not in outcome, outcome["error"]
    assert r2.connect_calls == 0, f"«Подключить» во время shutdown подключил устройство ({r2.connect_calls} раз)"


# --------------------------------------------------------------------------------------------------
# 6. shutdown после хука закрывает хаб как без хука
# --------------------------------------------------------------------------------------------------

_WITH_AND_WITHOUT_HOOK = pytest.mark.parametrize("use_hook", [False, True], ids=["no_hook", "after_hook"])


@_WITH_AND_WITHOUT_HOOK
def test_shutdown_removes_device_workers(hub: Hub, use_hook: bool) -> None:
    r1 = hub.add_robot("r1")
    r2 = hub.add_robot("r2")
    assert {"dev_r1", "dev_r2"} <= set(hub.ctx.worker_manager.workers), "обвязка: воркеры устройств не созданы"
    if use_hook:
        hub.hook()
        wait_entered(r1, "r1: ")
        wait_entered(r2, "r2: ")
    hub.shutdown()
    left = sorted(name for name in hub.ctx.worker_manager.workers if name.startswith("dev_"))
    assert left == [], f"после shutdown остались воркеры устройств: {left}"


@_WITH_AND_WITHOUT_HOOK
def test_shutdown_closes_thread_scope(hub: Hub, use_hook: bool) -> None:
    scope = hub.scope
    assert scope is not None, "обвязка: область потоков плагина не взята"
    scope.spawn(lambda *_: None, name="c60b-before")  # пока область открыта, spawn работает
    r1 = hub.add_robot("r1")
    if use_hook:
        hub.hook()
        wait_entered(r1)
    hub.shutdown()
    with pytest.raises(ScopeClosedError):
        scope.spawn(lambda *_: None, name="x")


@_WITH_AND_WITHOUT_HOOK
def test_shutdown_disconnects_drivers(hub: Hub, use_hook: bool) -> None:
    r1 = hub.add_robot("r1")
    r2 = hub.add_robot("r2")
    if use_hook:
        hub.hook()
        wait_entered(r1, "r1: ")
        wait_entered(r2, "r2: ")
    hub.shutdown()
    assert [r1.is_connected, r2.is_connected] == [False, False]
    assert [r1.disconnect_calls >= 1, r2.disconnect_calls >= 1] == [True, True]


@_WITH_AND_WITHOUT_HOOK
def test_shutdown_reports_unconfirmed_stop_to_health(hub: Hub, use_hook: bool) -> None:
    text = "стоп не подтверждён роботом"
    r1 = hub.add_robot("r1", unconfirmed_text=text)
    if use_hook:
        hub.hook()
        wait_entered(r1)
    hub.shutdown()
    time.sleep(_SETTLE_S)
    calls = [c for c in hub.ctx.health.report_error.call_args_list if c.kwargs.get("context") == _STOP_ECHO_CONTEXT]
    assert [(str(c.args[0]), c.kwargs.get("device_id")) for c in calls] == [(text, "r1")], calls


def test_robot_present_before_hook_gets_exactly_one_stop_over_whole_close(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    hub.hook()
    wait_entered(r1)
    hub.shutdown()
    time.sleep(_SETTLE_S)
    assert r1.stop_count() == _ONE, f"робот, бывший до хука, получил стопов: {r1.stop_count()}"


def test_robot_added_after_hook_gets_exactly_one_stop_at_shutdown(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    hub.hook()
    wait_entered(r1, "робот до хука: ")
    late = hub.add_robot("late", workers=False)  # появился после хука
    hub.shutdown()
    time.sleep(_SETTLE_S)
    assert late.stop_count() == _ONE, f"робот, добавленный после хука, получил стопов: {late.stop_count()}"


# --------------------------------------------------------------------------------------------------
# 7. shutdown ждёт стоп-запросы хука (или срок)
# --------------------------------------------------------------------------------------------------


def test_shutdown_returns_only_after_hook_stop_requests_finished(hub: Hub) -> None:
    r1 = hub.add_robot("r1", mode="slow")
    hub.hook()
    wait_entered(r1)
    assert r1.stops[0].done_at is None, "обвязка: медленный стоп уже закончился до shutdown"
    hub.shutdown()
    finished = r1.stops[0].done_at is not None  # снято сразу по возврату shutdown
    assert finished, f"shutdown вернулся раньше конца стоп-запроса хука (стоп идёт {_SLOW_STOP_S} с)"


def test_shutdown_returns_after_deadline_when_hook_stop_never_finishes(hub: Hub) -> None:
    r1 = hub.add_robot("r1", mode="hang")
    hub.hook()
    wait_entered(r1)
    deadline = r1.stops[0].deadline
    t_end = hub.shutdown()
    assert t_end >= deadline - _STOP_TOLERANCE_S, f"shutdown вернулся за {deadline - t_end:.3f} с до срока стопа"
    assert t_end <= deadline + _PAST_DEADLINE_S, f"shutdown вернулся через {t_end - deadline:.3f} с после срока"
    assert r1.stop_count() == _ONE


# --------------------------------------------------------------------------------------------------
# 8. Хук после shutdown и без configure
# --------------------------------------------------------------------------------------------------


def test_hook_after_shutdown_does_nothing_and_does_not_raise(hub: Hub) -> None:
    r1 = hub.add_robot("r1")
    hub.shutdown()
    assert r1.stop_count() == _ONE, "обвязка: shutdown без хука не дал одного стопа"
    run = hub.hook()
    time.sleep(_SETTLE_S)
    assert r1.stop_count() == _ONE, f"хук после shutdown дал ещё стоп: {r1.stop_count()}"
    assert run.elapsed <= _HOOK_BUDGET_S, run.elapsed


def test_hook_on_plugin_without_configure_does_not_raise() -> None:
    ctx = make_ctx()
    plugin = DeviceHubPlugin()
    run = run_hook(plugin, ctx, 5.0)
    assert run.elapsed <= _HOOK_BUDGET_S, run.elapsed


# --------------------------------------------------------------------------------------------------
# 9. Журнал
# --------------------------------------------------------------------------------------------------


def _plugin_log_lines(ctx: MagicMock, caplog: pytest.LogCaptureFixture) -> list[str]:
    """Строки журнала плагина: вызовы ``ctx.log*`` / ``ctx.logger*`` и записи ``logging``."""
    lines: list[str] = []
    for item in ctx.mock_calls:
        name, args = item[0], item[1]
        if name.startswith("log") and args:
            first = args[0]
            lines.append(str(first() if callable(first) else first))
    lines.extend(caplog.messages)
    return lines


def test_hook_writes_request_stop_line_to_plugin_log(hub: Hub, caplog: pytest.LogCaptureFixture) -> None:
    hub.add_robot("r1")
    with caplog.at_level(0):
        hub.hook()
    lines = [line for line in _plugin_log_lines(hub.ctx, caplog) if _HOOK_LOG in line]
    assert lines, f"в журнале плагина нет строки {_HOOK_LOG!r}: {_plugin_log_lines(hub.ctx, caplog)}"
