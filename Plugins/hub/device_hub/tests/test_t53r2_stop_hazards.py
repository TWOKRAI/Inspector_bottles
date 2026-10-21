"""Тесты-сторожа автора T5.3 круг 2: остановка роботов под одним сроком и один владелец потоков.

Purpose:
    Гонки и порядок стопа процесса (защёлка драйвера, параллельная рассылка менеджера, срок плагина). Записи
    ``STOP_REQ`` считаются НА СТОРОНЕ РОБОТА: action-хук pymodbus-сервера стенда видит каждый запрос записи до
    применения. Двойник робота умеет: не подтверждать стоп (``TLM_STOP_ACK`` заморожен), отклонить ближайшие записи
    ``STOP_REQ`` (``DEVICE_FAILURE``, счётчик ``fail_stops``), держать ответ на запись ``STOP_REQ`` или команды
    (запись применяется сразу, ответ клиенту задерживается).

Public API:
    Только тесты ``test_*``.

Stability: lite

Правила файла: ожидаемые значения — литералы; блокирующий вызов — в daemon-потоке с дедлайном (``bounded``);
область потоков теста закрывается в конце теста, выживших нет.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pymodbus.constants import ExcCodes

from multiprocess_framework.modules.base_manager import open_scope, unclosed_roots
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.device_hub import manager as device_manager
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.server.sim_robot import SimRobotServer
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, RecordingCore, bounded

_JOG = {"dir": 1, "spd": 20}
_CALL_S = 15.0
_CONNECT_S = 60.0
_SETTLE_S = 0.3
_STOP_REQ = REG["STOP_REQ"]
_ACK = REG["TLM_STOP_ACK"]
_CMD_FLAG = REG["CMD_FLAG"]
_SOFT_LEVEL = 1  # младшие 2 бита значения STOP_REQ (значение = stop_seq * 4 + уровень)
TEXT_STOPPING = "драйвер робота останавливается"
TEXT_UNCONFIRMED = "стоп не подтверждён роботом"
TEXT_NO_SPAWN = "RobotDriverV2 без spawn не запускает потоки"


# --------------------------------------------------------------------------------------------------
# Двойник робота
# --------------------------------------------------------------------------------------------------


class _Journal:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.stops: list[float] = []
        self.fail_stops = 0  # сколько ближайших записей STOP_REQ робот отклонит (DEVICE_FAILURE, быстро)
        self.hold_stop_s = 0.0
        self.hold_next_cmd_s = 0.0
        self.hold_ack_read_s = 0.0  # ответ на чтение, захватывающее TLM_STOP_ACK, держится (полуоткрытая связь)
        self.hold_ack_read_from = 0.0  # perf_counter, с которого держатся чтения (0 — сразу)
        self.cmd_reply_at = 0.0

    def count(self, since: float = 0.0) -> int:
        with self.lock:
            return len([t for t in self.stops if t >= since])

    def stamps(self) -> list[float]:
        with self.lock:
            return list(self.stops)


class _Core(RecordingCore):
    def __init__(self) -> None:
        self.silent = False
        self._frozen = 0
        super().__init__()

    def go_silent(self) -> None:
        self._frozen = self.regs[_ACK]
        self.silent = True

    def tick(self, dt_s: float | None = None) -> None:
        super().tick(dt_s)
        if self.silent:
            self.regs[_ACK] = self._frozen


class _Server(SimRobotServer):
    def __init__(self, *args: Any, journal: _Journal, **kwargs: Any) -> None:
        self._journal = journal
        super().__init__(*args, **kwargs)

    def _make_device(self):  # noqa: ANN202
        device = super()._make_device()
        inner, j = device.action, self._journal

        async def action(fc, start, addr, count, registers, values):  # noqa: ANN001, ANN202
            result = await inner(fc, start, addr, count, registers, values)
            late = time.perf_counter() >= j.hold_ack_read_from
            if int(fc) in (3, 4) and j.hold_ack_read_s and late and addr <= _ACK < addr + int(count):
                await asyncio.sleep(j.hold_ack_read_s)
                return result
            if int(fc) not in (6, 16) or values is None:
                return result
            span = range(addr, addr + max(int(count), len(values)))
            hold = 0.0
            with j.lock:
                if _STOP_REQ in span:
                    j.stops.append(time.perf_counter())
                    if j.fail_stops > 0:
                        j.fail_stops -= 1
                        return ExcCodes.DEVICE_FAILURE
                    hold = j.hold_stop_s
                elif _CMD_FLAG in span and j.hold_next_cmd_s:
                    hold, j.hold_next_cmd_s = j.hold_next_cmd_s, 0.0
            if hold:
                registers[addr - start : addr - start + len(values)] = values
                await asyncio.sleep(hold)
                if _CMD_FLAG in span:
                    j.cmd_reply_at = time.perf_counter()
            return result

        device.action = action
        return device


class _Rig(E2eRig):
    def __init__(self) -> None:
        self.journal = _Journal()
        super().__init__(core=_Core())

    def _start_server(self) -> None:
        from Services.robot_comm.tests.e2e_rig_v2 import _HOST, free_port  # noqa: PLC0415

        self.port = free_port()
        self.server = _Server(_HOST, self.port, ROBOT_UNIT_ID, core=self.core, journal=self.journal)
        bounded(self.server.start, 10.0)


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


class _Rec:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self.lock:
            self.items.append((path, payload))

    def at(self, path: str) -> list[Any]:
        with self.lock:
            return [p for k, p in self.items if k == path]


@contextmanager
def _scope() -> Iterator[Any]:
    scope = open_scope("t53r2", budget_s=6.0)
    try:
        yield scope
    finally:
        report = scope.close()
        assert list(report.survivors) == [], report.survivors


def _transport(port: int) -> dict:
    return {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID}


def _driver(rig: _Rig, rec: _Rec, spawn: Any, dev_id: str = "r1") -> RobotDriverV2:
    entry = DeviceEntry(id=dev_id, name=dev_id, kind="robot", protocol="delta_v2", transport=_transport(rig.port))
    drv = RobotDriverV2(entry, None, publish=rec, spawn=spawn)
    assert bounded(drv.connect, _CONNECT_S) is True
    drv.desired_connected = True
    return drv


def _manager(rec: _Rec, spawn: Any, rigs: dict[str, _Rig]) -> tuple[DeviceManager, dict[str, Any]]:
    mgr = DeviceManager(store=None, publish_cb=rec, spawn=spawn)
    drivers = {}
    for dev_id, rig in rigs.items():
        mgr.upsert(
            {"id": dev_id, "name": dev_id, "kind": "robot", "protocol": "delta_v2", "transport": _transport(rig.port)}
        )
        assert bounded(lambda d=dev_id: mgr.connect(d), _CONNECT_S) is True
        drivers[dev_id] = mgr.get_driver(dev_id)
        drivers[dev_id].desired_connected = True
    return mgr, drivers


def _moving(rig: _Rig) -> int:
    ticks = rig.core.ticks()
    return ticks[-1].moving if ticks else -1


def _until(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        assert time.monotonic() < end, what
        time.sleep(0.01)


@contextmanager
def _holding(drv: Any) -> Iterator[None]:
    """Оператор держит jog: подтверждения каждые 0.05 с до выхода из блока."""
    stop = threading.Event()

    def body() -> None:
        while not stop.is_set():
            try:
                drv.call("jog_hold", dict(_JOG))
            except Exception:  # noqa: BLE001 — подтверждения во время остановки
                pass
            stop.wait(0.05)

    t = threading.Thread(target=body, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(5.0)


def _jog_moving(drv: Any, rig: _Rig) -> None:
    assert bounded(lambda: drv.call("jog_hold", dict(_JOG)), _CALL_S)["status"] == "ok"
    _until(lambda: _moving(rig) == 1, 5.0, "jog не поехал")


def _program_running(drv: Any, rig: _Rig, legs: int = 20) -> None:
    points = {
        "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
        "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
    }
    program = Program(name="p", steps=tuple(Move(point="ab"[i % 2], kind="JOINT") for i in range(legs)))
    assert bounded(lambda: drv.start_program(program, points, None, name="p"), _CALL_S)["status"] == "ok"
    _until(lambda: _moving(rig) == 1, 5.0, "программа не поехала")


def _quiet(fn: Callable[[], object]) -> None:
    try:
        bounded(fn, _CALL_S)
    except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
        pass


# --------------------------------------------------------------------------------------------------
# REDS
# --------------------------------------------------------------------------------------------------


def test_one_silent_robot_one_stop_write_within_deadline(tmp_path: Path) -> None:
    with _Rig() as rig:
        registry = tmp_path / "devices.yaml"
        recipe = [
            {"id": "r1", "name": "r1", "kind": "robot", "protocol": "delta_v2", "transport": _transport(rig.port)}
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        assert plugin.cmd_device_connect({"device_id": "r1"})["status"] == "ok"
        bounded(plugin._process_conn_queue, _CONNECT_S)
        drv = plugin._manager.get_driver("r1")
        _jog_moving(drv, rig)
        with _holding(drv):
            rig.core.go_silent()
            t0 = time.perf_counter()
            bounded(lambda: plugin.shutdown(ctx), 10.0)
            elapsed = time.perf_counter() - t0
        time.sleep(_SETTLE_S)
        assert elapsed <= 2.5, elapsed
        assert rig.journal.count(t0) == 1, rig.journal.stamps()
        _until(lambda: _moving(rig) == 0, 1.0, "робот не остановился")
        # H3: нет эха -> health «стоп не подтверждён роботом» (решение §2)
        calls = [c for c in ctx.health.report_error.call_args_list if c.kwargs.get("context") == "device_hub.stop_echo"]
        assert [(str(c.args[0]), c.kwargs.get("device_id")) for c in calls] == [(TEXT_UNCONFIRMED, "r1")]


def test_silent_r1_does_not_delay_r2() -> None:
    rec = _Rec()
    with _Rig() as r1, _Rig() as r2, _scope() as scope:
        mgr, drv = _manager(rec, scope.spawn, {"r1": r1, "r2": r2})
        try:
            _program_running(drv["r1"], r1)
            _jog_moving(drv["r2"], r2)
            r1.core.go_silent()
            r1.journal.hold_stop_s = 1.5  # ответ r1 на запись стопа держится дольше таймаута транспорта
            t0 = time.perf_counter()
            with _holding(drv["r2"]):
                bounded(lambda: mgr.request_stop_all(time.monotonic() + 2.5), 10.0)
            first_r1 = [t for t in r1.journal.stamps() if t >= t0][0]
            first_r2 = [t for t in r2.journal.stamps() if t >= t0][0]
            assert abs(first_r2 - first_r1) <= 0.1, (first_r1 - t0, first_r2 - t0)
            assert r2.journal.count(t0) == 1
        finally:
            r1.journal.hold_stop_s = 0.0
            _quiet(mgr.shutdown)


def test_failed_write_retried_exactly_once() -> None:
    """Робот быстро отклоняет первые две записи стопа: драйвер пишет ровно дважды (повтор один), третьей попытки нет.
    Срок 2.5 с вмещает и третью (запись 0.0 + бюджет 2.0 с <= 2.5 с), поэтому останавливает её только счётчик
    попыток поколения, а не срок."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            _jog_moving(drv, rig)
            with _holding(drv):
                rig.journal.fail_stops = 2
                t0 = time.perf_counter()
                bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
                time.sleep(_SETTLE_S)
            assert rig.journal.count(t0) == 2, rig.journal.stamps()
        finally:
            _quiet(drv.disconnect)


def test_missing_echo_sets_last_error() -> None:
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            _jog_moving(drv, rig)
            rig.core.go_silent()
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
        finally:
            _quiet(drv.disconnect)
        assert TEXT_UNCONFIRMED in rec.at("devices.state.r1.last_error")


def test_operator_robot_stop_writes_after_latch() -> None:
    """Стоп оператора того же уровня, что защёлка процесса (SOFT после SOFT), пишется: защёлка гасит только повторы
    самого стопа процесса. Уровень выше защёлки (HARD после SOFT) проходит и через защёлку — им её не проверить."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            _jog_moving(drv, rig)
            t0 = time.perf_counter()
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)  # jog -> SOFT
            assert rig.journal.count(t0) == 1
            assert bounded(lambda: drv.call("abort", {"mode": 1}), _CALL_S) == {"status": "ok", "mode": 1}
            assert rig.journal.count(t0) == 2, rig.journal.stamps()
        finally:
            _quiet(drv.disconnect)


def test_start_program_racing_phase1_leaves_no_survivors_or_roots() -> None:
    rec = _Rec()
    roots_before = sorted(r["path"] for r in unclosed_roots())
    with _Rig() as rig:
        scope = open_scope("t53r2race", budget_s=6.0)
        mgr, drv = _manager(rec, scope.spawn, {"r1": rig})
        points = {"a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1)}
        program = Program(name="p", steps=(Move(point="a", kind="JOINT"),))
        replies: list[dict] = []
        go = threading.Event()

        def launcher() -> None:
            go.set()
            end = time.monotonic() + 1.0
            while time.monotonic() < end:
                try:
                    replies.append(drv["r1"].start_program(program, points, None, name="p"))
                except Exception as exc:  # noqa: BLE001 — ответ гонки
                    replies.append({"status": "exc", "message": repr(exc)})

        t = threading.Thread(target=launcher, daemon=True)
        t.start()
        assert go.wait(5.0)
        time.sleep(0.05)
        bounded(lambda: mgr.request_stop_all(time.monotonic() + 2.5), 10.0)
        t.join(5.0)
        assert not t.is_alive()
        report = scope.close(budget_s=max(0.0, 2.5))
        _quiet(mgr.shutdown)
        assert list(report.survivors) == [], report.survivors
        assert replies and replies[-1]["message"] == TEXT_STOPPING, replies[-3:]
    assert sorted(r["path"] for r in unclosed_roots()) == roots_before
    assert [t.name for t in threading.enumerate() if t.name.startswith(("rv2-", "t53r2race/"))] == []


def test_second_request_stop_all_after_scope_close_does_not_raise() -> None:
    rec = _Rec()
    with _Rig() as rig:
        scope = open_scope("t53r2second", budget_s=6.0)
        mgr, _drv = _manager(rec, scope.spawn, {"r1": rig})
        scope.close()
        t0 = time.perf_counter()
        bounded(lambda: mgr.request_stop_all(time.monotonic() + 2.5), 10.0)  # исключение — красный
        bounded(mgr.request_stop_all, 10.0)
        _quiet(mgr.shutdown)
        assert rig.journal.count(t0) == 1  # решение владельца 2026-10-19: простой робот получает один SOFT; второго нет


@pytest.mark.parametrize("failure", ["closed", "generic"])
def test_spawn_failure_still_writes_one_stop_per_moving_robot(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Rec()
    spy = _LogSpy()
    monkeypatch.setattr(device_manager, "logger", spy)
    closed = open_scope("t53r2closed", budget_s=1.0)
    closed.close()
    with _Rig() as r1, _Rig() as r2, _scope() as scope:

        def spawn(target: Any, *, name: str) -> Any:
            if name.startswith("stop-"):
                if failure == "closed":
                    return closed.spawn(target, name=name)  # ScopeClosedError
                raise RuntimeError("spawn отказал")
            return scope.spawn(target, name=name)

        mgr, drv = _manager(rec, spawn, {"r1": r1, "r2": r2})
        try:
            _program_running(drv["r1"], r1)
            # Программа идёт на роботе: пройдена первая нога, команда запуска принята. Стоп сразу после старта получил
            # бы вторую запись от О5 клиента (ADR-DH-009), её отдельно фиксирует test_stop_during_program_start_...
            _until(
                lambda: any(isinstance(p, dict) and p.get("done", 0) >= 1 for p in rec.at("devices.state.r1.program")),
                5.0,
                "программа не прошла первую ногу",
            )
            _jog_moving(drv["r2"], r2)
            t0 = time.perf_counter()
            with _holding(drv["r2"]):
                bounded(lambda: mgr.request_stop_all(time.monotonic() + 2.5), 10.0)
                time.sleep(_SETTLE_S)
            assert (r1.journal.count(t0), r2.journal.count(t0)) == (1, 1)
            # одна строка про отказ spawn на весь вызов (два робота): закрытая область — DEBUG, прочий отказ — WARNING
            lines = [lvl for lvl, text in spy.records if "не запущен" in text]
            assert lines == [{"closed": "debug", "generic": "warning"}[failure]], spy.records
        finally:
            _quiet(mgr.shutdown)


def test_jog_lock_held_stop_written_without_lock() -> None:
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            _jog_moving(drv, rig)
            t0 = time.perf_counter()
            assert drv._jog_tx_lock.acquire(timeout=5.0)  # шов: переход jog «завис» с замком
            try:
                bounded(lambda: drv.request_stop(time.monotonic() + 0.3), 5.0)
                assert rig.journal.count(t0) == 1  # записано, пока замок ещё держится
            finally:
                drv._jog_tx_lock.release()
            _until(lambda: _moving(rig) == 0, 1.0, "робот не остановился")
        finally:
            _quiet(drv.disconnect)


def test_driver_without_spawn_refuses_threaded_ops() -> None:
    rec = _Rec()
    with _Rig() as rig:
        drv = _driver(rig, rec, None)
        try:
            n_events = len(rig.core.events())
            assert bounded(lambda: drv.call("jog_hold", dict(_JOG)), _CALL_S) == {
                "status": "error",
                "message": TEXT_NO_SPAWN,
            }
            points = {"a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1)}
            with pytest.raises(RuntimeError, match="без spawn"):
                drv.start_program(Program(name="p", steps=(Move(point="a", kind="JOINT"),)), points, name="p")
            assert not any("JOG_CONT" in text for _, text in rig.core.events()[n_events:])
            assert _moving(rig) == 0
        finally:
            _quiet(drv.disconnect)


def test_rehold_after_failed_release_stop_then_process_stop_writes() -> None:
    """H-A: стоп prev, записанный в jog_hold до JOG_CONT, не закрывает защёлку для нового jog."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            _jog_moving(drv, rig)
            rig.journal.fail_stops = 1  # стоп release отклонён роботом: stop_sent остаётся False
            assert bounded(lambda: drv.call("jog_release", {}), _CALL_S)["status"] == "error"
            if not drv.is_connected:  # отказ записи транспорт считает обрывом: связь поднимается заново
                assert bounded(drv.connect, _CONNECT_S) is True
            reply = bounded(lambda: drv.call("jog_hold", dict(_JOG)), _CALL_S)  # путь стопа prev
            assert reply["status"] == "ok", reply
            _until(lambda: _moving(rig) == 1, 5.0, "новый jog не поехал")
            with _holding(drv):
                mark = time.perf_counter()
                bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
                time.sleep(_SETTLE_S)
            assert rig.journal.count(mark) == 1, rig.journal.stamps()
            _until(lambda: _moving(rig) == 0, 1.0, "новый jog не остановлен")
        finally:
            _quiet(drv.disconnect)


def test_jog_cont_in_flight_during_lockless_stop_gets_its_own_stop() -> None:
    """H-B: стоп процесса не взял замок перехода и лёг на робота РАНЬШЕ JOG_CONT (JOG_CONT в полёте) — jog_hold
    после возврата JOG_CONT пишет стоп этого jog сам и поводок не запускает."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            client = drv._client
            real_jog_cont = client.jog_cont
            jog_cont_returned: list[float] = []

            def slow_jog_cont(direction: int, speed: int) -> Any:
                time.sleep(0.6)  # шов: JOG_CONT уходит на провод ПОСЛЕ стопа процесса
                result = real_jog_cont(direction, speed)
                jog_cont_returned.append(time.perf_counter())
                return result

            client.jog_cont = slow_jog_cont  # type: ignore[method-assign]
            box: dict[str, Any] = {}
            t = threading.Thread(target=lambda: box.setdefault("r", drv.call("jog_hold", dict(_JOG))), daemon=True)
            t0 = time.perf_counter()
            t.start()
            _until(lambda: drv.state.view().jog_starting, 5.0, "jog_hold не начался")
            bounded(lambda: drv.request_stop(time.monotonic() + 0.2), 5.0)
            t.join(5.0)
            assert not t.is_alive()
            assert box["r"] == {"status": "error", "message": TEXT_STOPPING}
            stamps = [s for s in rig.journal.stamps() if s >= t0]
            assert len(stamps) == 2, [s - t0 for s in stamps]
            assert stamps[-1] >= jog_cont_returned[0]
            _until(lambda: _moving(rig) == 0, 1.5, "робот не остановился")
        finally:
            _quiet(drv.disconnect)


# --------------------------------------------------------------------------------------------------
# Ревью круга 2 (H1, H2, H4, H6, H7)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("echo", ["confirms", "silent"])
def test_job_in_motion_process_stop_one_write_tick_exits_fast(echo: str) -> None:
    """H1: задание CVT в ходе, стоп процесса, затем событие тика (как remove_worker) — одна запись, тик выходит."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        ev = threading.Event()

        def ticker() -> None:
            while not ev.is_set():
                drv.tick(ev)
                ev.wait(0.02)

        t = threading.Thread(target=ticker, daemon=True)
        client = drv._client
        real_kick = client.kick_heartbeat
        gate, parked = threading.Event(), threading.Event()
        gate.set()

        def kick() -> Any:
            # Шов-рандеву: пульс зовётся из on_poll задания ПОСЛЕ проверки события тика. Пока ворота закрыты, тик
            # стоит здесь и не видит обрыва задания роботом; следующий on_poll после открытия видит событие ->
            # ветка _JobStopped входится детерминированно
            if not gate.is_set() and drv.state.view().job_active:
                parked.set()
                gate.wait(5.0)
            return real_kick()

        client.kick_heartbeat = kick  # type: ignore[method-assign]
        try:
            assert drv.call("enqueue_job", {"x_mm": 400.0, "y_mm": 100.0})["status"] == "ok"
            t.start()
            _until(lambda: drv.state.view().job_active and _moving(rig) == 1, 10.0, "задание не поехало")
            time.sleep(0.2)
            gate.clear()
            assert parked.wait(5.0), "тик не встал на пульсе задания"
            if echo == "silent":
                rig.core.go_silent()
            t0 = time.perf_counter()
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
            set_at = time.perf_counter()
            ev.set()
            gate.set()
            t.join(5.0)
            exited = time.perf_counter() - set_at
            time.sleep(_SETTLE_S)
            assert not t.is_alive()
            assert rig.journal.count(t0) == 1, [x - t0 for x in rig.journal.stamps() if x >= t0]
            assert exited <= 0.5, exited
        finally:
            ev.set()
            gate.set()
            _quiet(drv.disconnect)


def test_driver_without_spawn_refuses_return_job_and_tick_keeps_it_visible() -> None:
    """H2: без spawn возврат отказан до очереди; возврат, попавший в очередь, тик не теряет молча."""
    rec = _Rec()
    with _Rig() as rig:
        drv = _driver(rig, rec, None)
        try:
            reply = drv.call("return_job", {"x_mm": 400.0, "y_mm": 100.0})
            assert reply == {"status": "error", "message": TEXT_NO_SPAWN}
            assert drv.snapshot()["return_queued"] == 0
            drv.state.enqueue_return((400.0, 100.0, 0.0))  # шов: возврат уже в очереди (путь до отказа)
            drv.tick(None)  # исключение — красный
            assert (drv.snapshot()["return_queued"], drv.snapshot()["returns_failed"]) == (0, 1)
            assert rec.at("devices.state.r1.last_error")[-1] == TEXT_NO_SPAWN
        finally:
            _quiet(drv.disconnect)


def test_abort_rejects_bad_level_with_constant_text() -> None:
    """H4: уровень стопа оператора — только 1..3 или SOFT/HARD/HALT; bool и строки-мусор отказаны без записи."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            t0 = time.perf_counter()
            for bad in ("abc", True, 99, 2.0, None):
                assert drv.call("abort", {"mode": bad}) == {"status": "error", "message": "неверный уровень стопа"}
            assert rig.journal.count(t0) == 0
            assert bounded(lambda: drv.call("abort", {"mode": "HARD"}), _CALL_S) == {"status": "ok", "mode": 2}
            assert rig.journal.count(t0) == 1
            assert bounded(lambda: drv.call("abort", {}), _CALL_S) == {"status": "ok", "mode": 1}  # умолчание SOFT
            assert rig.journal.count(t0) == 2
        finally:
            _quiet(drv.disconnect)


def test_echo_check_ignores_stop_of_previous_session() -> None:
    """H6: стоп оператора прошлой сессии, робот перезапущен (эхо 0), простой робот — не «не подтверждён»."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            assert bounded(lambda: drv.call("abort", {"mode": 1}), _CALL_S)["status"] == "ok"
            rig.restart(keep_regs=False)
            end = time.monotonic() + 20.0
            while not bounded(drv.connect, _CONNECT_S):
                assert time.monotonic() < end, "connect после рестарта робота"
                time.sleep(0.3)
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
        finally:
            _quiet(drv.disconnect)
        assert TEXT_UNCONFIRMED not in rec.at("devices.state.r1.last_error")


def test_echo_check_bounded_when_peer_read_is_held(tmp_path: Path) -> None:
    """H7: у обоих роботов чтение эха висит (полуоткрытая связь) — проверки эха не идут по очереди, <= 2.5 с."""
    with _Rig() as r1, _Rig() as r2:
        registry = tmp_path / "devices.yaml"
        recipe = [
            {"id": d, "name": d, "kind": "robot", "protocol": "delta_v2", "transport": _transport(r.port)}
            for d, r in (("r1", r1), ("r2", r2))
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        for d in ("r1", "r2"):
            assert plugin.cmd_device_connect({"device_id": d})["status"] == "ok"
        bounded(plugin._process_conn_queue, _CONNECT_S)
        d1, d2 = plugin._manager.get_driver("r1"), plugin._manager.get_driver("r2")
        _jog_moving(d1, r1)
        _jog_moving(d2, r2)
        with _holding(d1), _holding(d2):
            r1.journal.hold_ack_read_s = r2.journal.hold_ack_read_s = 3.0
            t0 = time.perf_counter()
            bounded(lambda: plugin.shutdown(ctx), 10.0)
            elapsed = time.perf_counter() - t0
        r1.journal.hold_ack_read_s = r2.journal.hold_ack_read_s = 0.0
        assert elapsed <= 2.5, elapsed
        assert (r1.journal.count(t0), r2.journal.count(t0)) == (1, 1)


def test_echo_reads_stop_at_budget_boundary_no_stop_thread_survives(tmp_path: Path) -> None:
    """H7 граница: эхо молчит, чтения эха с 0.7 с висят 3 с. Чтение не начинается позже ``срок - бюджет`` (0.5 с),
    поэтому после возврата shutdown живых потоков ``device_hub/stop-*`` нет."""
    with _Rig() as rig:
        registry = tmp_path / "devices.yaml"
        recipe = [
            {"id": "r1", "name": "r1", "kind": "robot", "protocol": "delta_v2", "transport": _transport(rig.port)}
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        assert plugin.cmd_device_connect({"device_id": "r1"})["status"] == "ok"
        bounded(plugin._process_conn_queue, _CONNECT_S)
        drv = plugin._manager.get_driver("r1")
        _jog_moving(drv, rig)
        with _holding(drv):
            rig.core.go_silent()
            t0 = time.perf_counter()
            rig.journal.hold_ack_read_from = t0 + 0.7
            rig.journal.hold_ack_read_s = 3.0
            bounded(lambda: plugin.shutdown(ctx), 10.0)
            elapsed = time.perf_counter() - t0
            alive = [t.name for t in threading.enumerate() if t.name.startswith("device_hub/stop-") and t.is_alive()]
        rig.journal.hold_ack_read_s = 0.0
        assert alive == []
        # Поздно начатое чтение держит замок транспорта: закрытие сокета в фазе 4 ждёт его, остановка выходит за срок
        assert elapsed <= 2.5, elapsed
        assert rig.journal.count(t0) == 1


def test_program_stop_after_g0_then_progress_does_not_repeat_stop() -> None:
    """Стоп процесса записан ПОСЛЕ g0 прогона, затем опрос с прогрессом: повтор on_progress (микроокно К1) не
    нужен — прогон видит стоп сам. Ровно одна запись STOP_REQ (рандеву в wait_done: стоп, затем on_poll)."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        client = drv._client
        real_wait = client.wait_done
        marks: dict[str, float] = {}

        def wait_done(seq: int, *, on_poll: Any = None) -> Any:
            if on_poll is not None and "t0" not in marks:
                marks["t0"] = time.perf_counter()
                drv.request_stop(time.monotonic() + 2.5)  # после sc_run, т.е. после g0 прогона
                on_poll(list(client._rd(REG["TLM_PROTO_VER"], 32)))  # первый опрос: прогресс меняется всегда
            return real_wait(seq, on_poll=on_poll)

        client.wait_done = wait_done  # type: ignore[method-assign]
        try:
            _program_running(drv, rig)
            _until(lambda: "t0" in marks, 5.0, "рандеву не случилось")
            _until(lambda: _moving(rig) == 0, 2.0, "робот не остановился")
            time.sleep(_SETTLE_S)
            assert rig.journal.count(marks["t0"]) == 1, [x - marks["t0"] for x in rig.journal.stamps()]
        finally:
            client.wait_done = real_wait  # type: ignore[method-assign]
            _quiet(drv.disconnect)


def test_second_process_stop_while_motion_alive_writes_once() -> None:
    """Защёлка стопа процесса: исполнитель программы жив (``_prog_alive``) и во втором вызове, но запись уже есть —
    второй ``request_stop`` с тем же сроком записи не даёт. Шов: ``run_chunks`` держит поток исполнителя после
    возврата (как застрявший ``wait_done``), поэтому уровень HARD из живого состояния второй раз ВЫЧИСЛЯЕТСЯ, и
    остановить запись может только защёлка (срок 2.5 с вмещает вторую попытку)."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        client = drv._client
        real_run_chunks = client.run_chunks
        gate = threading.Event()

        def held_run_chunks(*args: Any, **kwargs: Any) -> Any:
            try:
                return real_run_chunks(*args, **kwargs)
            finally:
                gate.wait(8.0)  # исполнитель не выходит, пока тест не откроет ворота

        client.run_chunks = held_run_chunks  # type: ignore[method-assign]
        try:
            _program_running(drv, rig)
            time.sleep(0.3)  # команды запуска приняты роботом: О5 клиента (повторный стоп) не вмешивается
            deadline = time.monotonic() + 2.5
            t0 = time.perf_counter()
            bounded(lambda: drv.request_stop(deadline), 10.0)
            _until(lambda: _moving(rig) == 0, 2.0, "робот не остановился")
            assert drv.state.view().program_active, "шов не держит исполнитель: проверка защёлки не имеет смысла"
            bounded(lambda: drv.request_stop(deadline), 10.0)
            time.sleep(_SETTLE_S)
            assert rig.journal.count(t0) == 1, [x - t0 for x in rig.journal.stamps() if x >= t0]
        finally:
            gate.set()
            client.run_chunks = real_run_chunks  # type: ignore[method-assign]
            _quiet(drv.disconnect)


class _LogSpy:
    """Подмена логгера менеджера: ``(уровень, текст)`` каждой записи (фасад пишет в LoggerManager или фолбэк)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, msg: str, *_a: Any, **_k: Any) -> bool:
        self.records.append((level, str(msg)))
        return True

    def debug(self, msg: str, *a: Any, **k: Any) -> bool:
        return self._add("debug", msg)

    def info(self, msg: str, *a: Any, **k: Any) -> bool:
        return self._add("info", msg)

    def warning(self, msg: str, *a: Any, **k: Any) -> bool:
        return self._add("warning", msg)

    def error(self, msg: str, *a: Any, **k: Any) -> bool:
        return self._add("error", msg)

    def exception(self, msg: str, *a: Any, **k: Any) -> bool:
        return self._add("error", msg)


def test_plugin_shutdown_scope_closed_spawn_is_quiet_and_writes_one_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Фаза 4 (``_on_shutdown`` -> ``request_stop_all``) идёт после ``scope.close``: ``spawn`` отвечает
    ``ScopeClosedError``, стоп идёт синхронно (защёлка ничего не пишет). Это штатный путь, не отказ: записи выше
    DEBUG про «поток стоп-запроса не запущен» быть не должно, запись на робота ровно одна."""
    spy = _LogSpy()
    monkeypatch.setattr(device_manager, "logger", spy)
    with _Rig() as rig:
        registry = tmp_path / "devices.yaml"
        recipe = [
            {"id": "r1", "name": "r1", "kind": "robot", "protocol": "delta_v2", "transport": _transport(rig.port)}
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        assert plugin.cmd_device_connect({"device_id": "r1"})["status"] == "ok"
        bounded(plugin._process_conn_queue, _CONNECT_S)
        drv = plugin._manager.get_driver("r1")
        _jog_moving(drv, rig)
        with _holding(drv):
            t0 = time.perf_counter()
            bounded(lambda: plugin.shutdown(ctx), 10.0)
        time.sleep(_SETTLE_S)
        assert rig.journal.count(t0) == 1, rig.journal.stamps()
    noisy = [r for r in spy.records if "не запущен" in r[1] and r[0] != "debug"]
    assert noisy == [], noisy


def test_stop_during_program_start_at_most_two_writes() -> None:
    """Документирует О5 клиента (ADR-DH-009): стоп сразу после старта программы — одна запись, а если робот принял
    команду запуска уже после стопа, вторая (свой стоп команде). Больше двух не бывает; робот в итоге стоит."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            points = {
                "a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1),
                "b": Point(name="b", x=300, y=-210, z=-40, rz=-100, hand=1),
            }
            program = Program(name="p", steps=tuple(Move(point="ab"[i % 2], kind="JOINT") for i in range(20)))
            t0 = time.perf_counter()
            assert bounded(lambda: drv.start_program(program, points, None, name="p"), _CALL_S)["status"] == "ok"
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
            time.sleep(_SETTLE_S)
            writes = rig.journal.count(t0)
            assert 1 <= writes <= 2, rig.journal.stamps()
            _until(lambda: _moving(rig) == 0, 2.0, "робот не остановился")
        finally:
            _quiet(drv.disconnect)


# --------------------------------------------------------------------------------------------------
# Решение владельца 2026-10-19: выключаемый подключённый робот получает стоп и в покое (SOFT)
# --------------------------------------------------------------------------------------------------


def _stop_req_level(rig: _Rig) -> int:
    """Уровень последней записи STOP_REQ на стороне робота (значение регистра & 3)."""
    return int(rig.core.regs[_STOP_REQ]) & 3


def test_plugin_shutdown_two_idle_robots_one_soft_write_each(tmp_path: Path) -> None:
    with _Rig() as r1, _Rig() as r2:
        registry = tmp_path / "devices.yaml"
        recipe = [
            {"id": dev_id, "name": dev_id, "kind": "robot", "protocol": "delta_v2", "transport": _transport(rig.port)}
            for dev_id, rig in (("r1", r1), ("r2", r2))
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        for dev_id in ("r1", "r2"):
            assert plugin.cmd_device_connect({"device_id": dev_id})["status"] == "ok"
        bounded(plugin._process_conn_queue, _CONNECT_S)
        assert sorted(plugin._manager.connected_ids()) == ["r1", "r2"]
        assert (_moving(r1), _moving(r2)) == (0, 0)  # оба простаивают: пустой зелени нет
        t0 = time.perf_counter()
        bounded(lambda: plugin.shutdown(ctx), 10.0)
        elapsed = time.perf_counter() - t0
        time.sleep(_SETTLE_S)
        assert elapsed <= 2.5, elapsed
        assert (r1.journal.count(t0), r2.journal.count(t0)) == (1, 1), (r1.journal.stamps(), r2.journal.stamps())
        assert (_stop_req_level(r1), _stop_req_level(r2)) == (_SOFT_LEVEL, _SOFT_LEVEL)


def test_individual_disconnect_stops_only_that_idle_robot() -> None:
    rec = _Rec()
    with _Rig() as r1, _Rig() as r2, _scope() as scope:
        mgr, _drv = _manager(rec, scope.spawn, {"r1": r1, "r2": r2})
        try:
            assert (_moving(r1), _moving(r2)) == (0, 0)
            t0 = time.perf_counter()
            bounded(lambda: mgr.disconnect("r1"), _CALL_S)
            time.sleep(_SETTLE_S)
            assert r1.journal.count(t0) == 1, r1.journal.stamps()
            assert _stop_req_level(r1) == _SOFT_LEVEL
            assert r2.journal.count(t0) == 0, r2.journal.stamps()  # подключённый сосед не тронут
            assert mgr.connected_ids() == ["r2"]
        finally:
            _quiet(mgr.shutdown)


def test_idle_robot_disconnect_after_process_stop_no_second_write() -> None:
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        assert _moving(rig) == 0
        t0 = time.perf_counter()
        bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
        assert rig.journal.count(t0) == 1, rig.journal.stamps()
        assert _stop_req_level(rig) == _SOFT_LEVEL
        bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)  # повтор фазы 1
        bounded(drv.disconnect, _CALL_S)  # фаза 4
        time.sleep(_SETTLE_S)
        assert rig.journal.count(t0) == 1, rig.journal.stamps()


def test_idle_robot_shutdown_after_operator_stop_still_writes() -> None:
    """Один стоп на каждое выключение: стоп оператора этого поколения выключение не покрывает (2 записи), повторный
    вызов в том же выключении (второй request_stop, disconnect) третьей не даёт."""
    rec = _Rec()
    with _Rig() as rig, _scope() as scope:
        drv = _driver(rig, rec, scope.spawn)
        try:
            assert _moving(rig) == 0
            t0 = time.perf_counter()
            assert bounded(lambda: drv.call("abort", {"mode": 1}), _CALL_S) == {"status": "ok", "mode": 1}
            assert rig.journal.count(t0) == 1, rig.journal.stamps()
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
            time.sleep(_SETTLE_S)
            assert rig.journal.count(t0) == 2, rig.journal.stamps()
            assert _stop_req_level(rig) == _SOFT_LEVEL
            bounded(lambda: drv.request_stop(time.monotonic() + 2.5), 10.0)
            bounded(drv.disconnect, _CALL_S)
            time.sleep(_SETTLE_S)
            assert rig.journal.count(t0) == 2, rig.journal.stamps()
        finally:
            _quiet(drv.disconnect)


def test_shutdown_after_jog_release_long_ago_writes_one_stop(tmp_path: Path) -> None:
    with _Rig() as rig:
        registry = tmp_path / "devices.yaml"
        recipe = [
            {"id": "r1", "name": "r1", "kind": "robot", "protocol": "delta_v2", "transport": _transport(rig.port)}
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        assert plugin.cmd_device_connect({"device_id": "r1"})["status"] == "ok"
        bounded(plugin._process_conn_queue, _CONNECT_S)
        drv = plugin._manager.get_driver("r1")
        _jog_moving(drv, rig)
        t0 = time.perf_counter()
        assert bounded(lambda: drv.call("jog_release", {}), _CALL_S)["status"] == "ok"
        _until(lambda: _moving(rig) == 0, 2.0, "робот не остановился после отпускания jog")
        assert rig.journal.count(t0) == 1, rig.journal.stamps()  # стоп отпускания записан
        time.sleep(1.0)
        bounded(lambda: plugin.shutdown(ctx), 10.0)
        time.sleep(_SETTLE_S)
        assert rig.journal.count(t0) == 2, rig.journal.stamps()  # ровно одна запись выключения сверх отпускания
