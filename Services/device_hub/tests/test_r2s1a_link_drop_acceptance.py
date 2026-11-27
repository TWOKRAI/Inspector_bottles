"""Слепая приёмка R2-S1a, часть 2 (A11-A15): после обрыва движение не уходит по другому сеансу, STOP не теряется.

Настоящие ``RobotDriverV2`` / ``RobotDriver`` (v1) / ``VfdDriver`` по TCP на ``127.0.0.1``. Робота изображает ядро
sim (``RobotSimCoreV2`` / ``RobotSimCore``), отданное сервером ``LoopbackServer`` из приёмки части 1: он пишет все
кадры и обрывает связь. Живой робот не трогается.

Как «операция допущена до обрыва и пишет после него» делается без знания устройства автора:
    1. посторонний поток читает через ``drv.transport`` регистр 0x0F00; сервер держит ответ — замок устройства занят;
    2. операция запускается: драйвер её допускает (связь есть), её первый обмен ждёт замок;
    3. сервер рвёт связь; посторонний читатель получает ошибку, операция продолжает.
Всё, что записано после отпускания, — запись после обрыва.

Режим ``fin-reconnected``: связь поднята заново раньше, чем операция продолжила (``on_error`` настоящего
``ModbusDevice``, отданного драйверу через ``transport=``, зовёт ``connect()`` под замком устройства). Флаг связи
снова «есть», и отказать может только сверка сеанса.

Операции из ``OP_SPECS`` драйвера v2:
    движение — ``jog_hold``, ``jog_step`` (ход), ``servo`` (on), ``enqueue_job``, ``return_job`` (задания),
    ``program_run``, ``draw_polyline`` (программа), ``park`` (ход домой и серво OFF);
    не движение — ``stop``, ``abort``, ``program_abort``, ``jog_release`` (остановка: должны проходить всегда),
    ``get_telemetry``, ``exchange_log_get``, ``exchange_log_set``, ``point_capture`` (чтение / журнал / файл),
    ``do_set`` (дискретный выход, ходом не является), ``param_set``, ``param_apply``, ``calib_belt`` (параметры).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.registry.entry import DeviceEntry
from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.tests.test_r2s1a_transport_acceptance import Call, Frame, LoopbackServer, run
from Services.robot_comm.programs import Move, Point, Program
from Services.robot_comm.robot_data import save_points, save_program
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.store import RobotDataStore

# Адреса карты v2 — литералы (protocol-spec): ожидания не выводятся из проверяемого кода
_CMD_FIRST, _CMD_LAST = 0x1000, 0x100F
_JOG_LEASE = 0x1022
_SC_FIRST, _SC_LAST = 0x1400, 0x1400 + 330 - 1
_STOP_REQ = 0x1021
_TLM_PROTO_VER = 0x1040
_OP_SC_RUN = 0x30
_VFD_FIRST, _VFD_LAST = 0x1200, 0x1204  # мост ПЧ
_V1_REG_STOP = 0x1106
_PROBE_ADDR = 0x0F00  # свободный регистр для постороннего чтения

_DEV = "rv2"
_JOG_STEP = {"dx": 1.0, "dy": 0.0, "spd": 20}
_JOG_HOLD = {"dir": 1, "spd": 20}
_DRAW = {"points": [{"x_mm": 300.0, "y_mm": 0.0}, {"x_mm": 310.0, "y_mm": 0.0}]}


def _overlaps(frame: Frame, first: int, last: int) -> bool:
    return frame.addr <= last and frame.addr + frame.count - 1 >= first


def _motion_writes(frames: list[Frame]) -> list[tuple[int, tuple[int, ...]]]:
    """Записи в регистры команд, буфер программы и аренду jog."""
    ranges = ((_CMD_FIRST, _CMD_LAST), (_SC_FIRST, _SC_LAST), (_JOG_LEASE, _JOG_LEASE))
    return [(f.addr, f.values[:4]) for f in frames if f.fc in (6, 16) and any(_overlaps(f, a, b) for a, b in ranges)]


def _writes_at(frames: list[Frame], address: int) -> list[Frame]:
    return [f for f in frames if f.fc in (6, 16) and f.addr == address]


_MODES = ["fin", "rst", "fin-reconnected"]


def _kind(mode: str) -> str:
    return mode.split("-")[0]


class _Redial:
    """``on_error`` устройства: взведён — один раз поднять связь тут же, под замком устройства."""

    def __init__(self) -> None:
        self.device: ModbusDevice | None = None
        self.armed = False

    def __call__(self, _message: str) -> None:
        if self.armed:
            self.armed = False
            self.device.connect()


def _wait(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        assert time.monotonic() < end, f"не дождались за {deadline_s} с: {what}"
        time.sleep(0.02)


class _Sim:
    """Ядро sim + поток тиков; ``frozen`` — ядро не тикает (эхо стопа не приходит)."""

    def __init__(self, core: Any) -> None:
        self.core = core
        self.server = LoopbackServer(core)
        self.frozen = threading.Event()
        self.errors: list[BaseException] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._tick, name="r2s1a-sim", daemon=True)
        self._thread.start()

    def _tick(self) -> None:
        last = time.perf_counter()
        while not self._stop.is_set():
            time.sleep(0.01)
            now = time.perf_counter()
            if not self.frozen.is_set():
                with self.server.store_lock:
                    try:
                        self.core.tick(min(now - last, 0.1))
                    except BaseException as exc:  # noqa: BLE001
                        self.errors.append(exc)
                        return
            last = now

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2.0)
        self.server.close()


class _Rec:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self._items.append((path, dict(payload) if isinstance(payload, dict) else payload))

    def program_states(self) -> list[str]:
        with self._lock:
            return [p["state"] for path, p in self._items if path == f"devices.state.{_DEV}.program"]


def _entry(device_id: str, protocol: str, port: int, params: dict | None = None) -> DeviceEntry:
    return DeviceEntry(
        id=device_id,
        name=device_id,
        kind="robot",
        protocol=protocol,
        transport={
            "type": "tcp",
            "host": "127.0.0.1",
            "port": port,
            "unit_id": 2,
            "timeout_sec": 4.0,
            "retries": 1,
        },
        params=dict(params or {}),
    )


class _Rig:
    def __init__(self, sim: _Sim, drv: Any, rec: _Rec, redial: _Redial | None = None) -> None:
        self.redial = redial
        self.sim = sim
        self.srv = sim.server
        self.drv = drv
        self.rec = rec

    def call(self, op: str, args: dict | None = None) -> dict:
        return run(lambda: self.drv.call(op, dict(args or {})))

    def reconnect(self) -> None:
        end = time.monotonic() + 20.0
        while not self.drv.is_connected:
            assert time.monotonic() < end, "драйвер не переподключился за 20 с"
            run(lambda: self.drv.tick(None), 20.0)
            time.sleep(0.2)

    def wait_robot_idle(self) -> None:
        from Services.robot_comm.core.protocol_v2 import REG

        def idle() -> bool:
            with self.srv.store_lock:
                return self.sim.core.regs[REG["TLM_ACTIVITY"]] == 0

        time.sleep(0.2)
        _wait(idle, 60.0, "робот sim в простое")

    def drop_seen_by_reader(self, kind: str) -> None:
        """Обрыв, замеченный посторонним чтением (исход чтения здесь не проверяется)."""
        rule = self.srv.on_next(lambda f: f.addr == _PROBE_ADDR, kind)
        Call(lambda: self.drv.transport.read_registers(_PROBE_ADDR, 1)).join()
        assert rule.entered.is_set(), "посторонний читатель не дошёл до сервера"

    def release(self, held: Any, reader: Call) -> int:
        """Отпустить удержанный ответ (обрыв). Возврат: метка журнала на момент обрыва."""
        if self.redial is not None:
            self.redial.armed = True
        mark = self.srv.mark()
        held.release.set()
        reader.join()
        return mark

    def admitted_then_drop(self, action: Callable[[], Any], kind: str) -> tuple[int, Call]:
        """Запустить ``action``, пока замок устройства занят чужим чтением, и оборвать связь. Возврат: метка, вызов."""
        held = self.srv.on_next(lambda f: f.addr == _PROBE_ADDR, kind, hold=True)
        reader = Call(lambda: self.drv.transport.read_registers(_PROBE_ADDR, 1))
        assert held.entered.wait(10.0), "посторонний читатель не дошёл до сервера"
        pending = Call(action)
        time.sleep(0.6)
        mark = self.release(held, reader)
        pending.join(30.0)
        return mark, pending


@contextmanager
def _v2(tmp_path: Path | None = None, mode: str = "fin") -> Iterator[_Rig]:
    sim = _Sim(RobotSimCoreV2())
    scope = open_scope("r2s1a", budget_s=6.0)
    rec = _Rec()
    store = None
    if tmp_path is not None:
        store = RobotDataStore(tmp_path / "robot")
        points = {
            "a": Point(name="a", x=300.0, y=0.0, z=-20.0, rz=0.0, hand=1, frame=None),
            "b": Point(name="b", x=310.0, y=0.0, z=-20.0, rz=0.0, hand=1, frame=None),
        }
        save_points(store, _DEV, points, base_rev=None)
        program = Program(name="p1", steps=(Move(point="a", kind="JOINT"), Move(point="b", kind="JOINT")))
        save_program(store, _DEV, program, base_rev=None)
    drv = None
    try:
        entry = _entry(_DEV, "delta_v2", sim.server.port)
        redial = None
        transport = None
        if mode == "fin-reconnected":
            redial = _Redial()
            config = ModbusConfig(host="127.0.0.1", port=sim.server.port, unit_id=2, timeout_sec=4.0, retries=1)
            transport = redial.device = ModbusDevice(config, on_error=redial)
        drv = RobotDriverV2(entry, None, publish=rec, spawn=scope.spawn, store=store, transport=transport)
        assert run(drv.connect, 60.0) is True
        drv.desired_connected = True
        yield _Rig(sim, drv, rec, redial)
        assert sim.errors == [], f"ядро sim упало: {sim.errors}"
    finally:
        if drv is not None:
            closing = Call(drv.disconnect)
            closing._thread.join(20.0)
        scope.close()
        sim.close()


class _Ticker:
    """``drv.tick`` в фоне; ``stop_event`` тот же, что видит драйвер, — ожидание задания им прерывается."""

    def __init__(self, drv: Any) -> None:
        self._drv = drv
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="r2s1a-hub-tick", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._drv.tick(self._stop)
            time.sleep(0.1)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(20.0)
        assert not self._thread.is_alive(), "тик драйвера повис"


# --------------------------------------------------------------------------------------------------
# A11: операции движения
# --------------------------------------------------------------------------------------------------


def test_a11_op_list_matches_op_specs() -> None:
    """Каждая операция драйвера отнесена к одному из двух списков (см. докстринг модуля)."""
    motion = ["jog_hold", "jog_step", "servo", "enqueue_job", "return_job", "program_run", "draw_polyline", "park"]
    not_motion = [
        "stop",
        "abort",
        "program_abort",
        "jog_release",
        "get_telemetry",
        "exchange_log_get",
        "exchange_log_set",
        "point_capture",
        "do_set",
        "param_set",
        "param_apply",
        "calib_belt",
    ]
    assert sorted(spec.name for spec in RobotDriverV2.OP_SPECS) == sorted(motion + not_motion)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("op", "args"),
    [("servo", {"on": True}), ("jog_step", _JOG_STEP), ("jog_hold", _JOG_HOLD)],
    ids=["servo_on", "jog_step", "jog_hold"],
)
def test_a11_command_admitted_before_drop_is_refused(op: str, args: dict, mode: str) -> None:
    with _v2(mode=mode) as rig:
        # парная проверка ДО обрыва: эта же операция на этом же сервере пишет команду
        mark = rig.srv.mark()
        reply = rig.call(op, args)
        assert reply["status"] == "ok", reply
        assert _motion_writes(rig.srv.frames(mark)) != []
        if op == "jog_hold":
            assert rig.call("jog_release")["status"] == "ok"
        rig.wait_robot_idle()

        mark, pending = rig.admitted_then_drop(lambda: rig.drv.call(op, dict(args)), _kind(mode))
        time.sleep(0.5)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert pending.value["status"] == "error", pending.value


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("op", "args"),
    [("draw_polyline", _DRAW), ("program_run", {"name": "p1"})],
    ids=["draw_polyline", "program_run"],
)
def test_a11_program_admitted_before_drop_writes_nothing(tmp_path: Path, op: str, args: dict, mode: str) -> None:
    with _v2(tmp_path, mode=mode) as rig:
        mark, pending = rig.admitted_then_drop(lambda: rig.drv.call(op, dict(args)), _kind(mode))
        assert pending.value["status"] == "ok", pending.value  # операция допущена
        _wait(lambda: rig.rec.program_states()[-1:] not in ([], ["running"]), 40.0, "конец потока программы")
        time.sleep(0.3)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert rig.rec.program_states()[-1] in ("failed", "aborted")
        # парная проверка: после переподключения та же программа доходит до буфера и исполняется
        rig.reconnect()
        rig.wait_robot_idle()
        mark = rig.srv.mark()
        reply = rig.call(op, args)
        assert reply["status"] == "ok", reply
        _wait(lambda: rig.rec.program_states()[-1:] == ["done"], 40.0, "программа после переподключения")
        assert [f for f in rig.srv.frames(mark) if f.fc == 16 and _overlaps(f, _SC_FIRST, _SC_LAST)] != []


@pytest.mark.parametrize("mode", _MODES)
def test_a11_jog_lease_stops_writing_after_drop(mode: str) -> None:
    with _v2(mode=mode) as rig:
        stop_pulse = threading.Event()

        def hold_button() -> None:
            while not stop_pulse.is_set():
                rig.drv.call("jog_hold", dict(_JOG_HOLD))
                time.sleep(0.05)

        assert rig.call("jog_hold", _JOG_HOLD)["status"] == "ok"
        button = threading.Thread(target=hold_button, daemon=True)
        button.start()
        try:
            # парная проверка: поводок пишет аренду, пока связь цела
            _wait(lambda: len(_writes_at(rig.srv.frames(), _JOG_LEASE)) >= 2, 10.0, "записи аренды jog")
            held = rig.srv.on_next(lambda f: f.addr == _PROBE_ADDR, _kind(mode), hold=True)
            reader = Call(lambda: rig.drv.transport.read_registers(_PROBE_ADDR, 1))
            assert held.entered.wait(10.0)
            time.sleep(1.0)  # дольше периода аренды: поток поводка встал на замок устройства
            stop_pulse.set()  # кнопка отпущена до обрыва: новый JOG_CONT после переподключения был бы законным
            button.join(10.0)
            mark = rig.release(held, reader)
            time.sleep(1.0)
        finally:
            stop_pulse.set()
            button.join(10.0)
        assert _motion_writes(rig.srv.frames(mark)) == []


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("enqueue_job", {"x_mm": 300.0, "y_mm": 0.0, "e_capture": 0}),
        ("return_job", {"x_mm": 300.0, "y_mm": 0.0, "z_mm": -20.0}),
    ],
    ids=["enqueue_job", "return_job"],
)
def test_a11_queued_job_admitted_before_drop_is_not_sent(op: str, args: dict, kind: str) -> None:
    """Задание принято (связь была), тик отдаёт его уже после обрыва и переподключения."""
    with _v2() as rig:
        reply = rig.call(op, args)
        assert reply["status"] == "ok", reply
        rig.drop_seen_by_reader(kind)
        mark = rig.srv.mark()
        ticker = _Ticker(rig.drv)
        try:
            time.sleep(3.0)
        finally:
            ticker.close()
        assert _motion_writes(rig.srv.frames(mark)) == []
        # парная проверка: новое задание после переподключения уходит
        rig.reconnect()
        rig.wait_robot_idle()
        mark = rig.srv.mark()
        reply = rig.call(op, args)
        assert reply["status"] == "ok", reply
        ticker = _Ticker(rig.drv)
        try:
            _wait(lambda: _motion_writes(rig.srv.frames(mark)) != [], 15.0, "новое задание на проводе")
        finally:
            ticker.close()


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a11_park_admitted_before_drop_is_not_executed(kind: str) -> None:
    with _v2() as rig:
        assert rig.call("park")["status"] == "ok"
        rig.drop_seen_by_reader(kind)
        mark = rig.srv.mark()
        ticker = _Ticker(rig.drv)
        try:
            time.sleep(3.0)
        finally:
            ticker.close()
        assert _motion_writes(rig.srv.frames(mark)) == []
        # парная проверка: новый park после переподключения пишет команду
        rig.reconnect()
        rig.wait_robot_idle()
        mark = rig.srv.mark()
        assert rig.call("park")["status"] == "ok"
        ticker = _Ticker(rig.drv)
        try:
            _wait(lambda: _motion_writes(rig.srv.frames(mark)) != [], 15.0, "команда park на проводе")
        finally:
            ticker.close()


# --------------------------------------------------------------------------------------------------
# A12: программа из нескольких кусков в момент обрыва
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", _MODES)
def test_a12_running_program_next_chunk_is_refused_and_driver_recovers(mode: str) -> None:
    points = [{"x_mm": 250.0 + 2.0 * i, "y_mm": 10.0 * (i % 2)} for i in range(60)]

    def sc_runs(frames: list[Frame]) -> list[Frame]:
        return [f for f in frames if f.fc == 16 and f.addr == 0x1001 and f.values[1:2] == (_OP_SC_RUN,)]

    with _v2(mode=mode) as rig:
        reply = rig.call("draw_polyline", {"points": points})
        assert reply["status"] == "ok", reply
        assert reply["total"] >= 56, reply  # половина буфера — 27 записей: кусков не меньше двух
        _wait(lambda: len(sc_runs(rig.srv.frames())) >= 1, 20.0, "первый SC_RUN")
        held = rig.srv.on_next(lambda f: f.addr == _PROBE_ADDR, _kind(mode), hold=True)
        reader = Call(lambda: rig.drv.transport.read_registers(_PROBE_ADDR, 1))
        assert held.entered.wait(10.0)
        assert rig.rec.program_states()[-1] == "running", "программа кончилась до обрыва"
        time.sleep(0.4)
        mark = rig.release(held, reader)
        _wait(lambda: rig.rec.program_states()[-1] != "running", 90.0, "конец потока программы")
        time.sleep(0.3)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert rig.rec.program_states()[-1] in ("failed", "aborted")

        rig.reconnect()
        rig.wait_robot_idle()
        mark = rig.srv.mark()
        reply = rig.call("jog_step", _JOG_STEP)
        assert reply["status"] == "ok", reply
        assert _motion_writes(rig.srv.frames(mark)) != []


# --------------------------------------------------------------------------------------------------
# A13: STOP после обрыва
# --------------------------------------------------------------------------------------------------


def _drop_seen_by_telemetry(rig: _Rig, kind: str) -> None:
    rule = rig.srv.on_next(lambda f: f.addr == _TLM_PROTO_VER, kind)
    Call(lambda: rig.drv.call("get_telemetry", {})).join()
    assert rule.entered.is_set()


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("how", ["request_stop", "disconnect"])
def test_a13_stop_after_drop_writes_exactly_one_stop_req(how: str, kind: str) -> None:
    with _v2() as rig:
        _drop_seen_by_telemetry(rig, kind)
        mark = rig.srv.mark()
        if how == "request_stop":
            run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
        else:
            run(rig.drv.disconnect, 30.0)
        time.sleep(0.5)
        assert len(_writes_at(rig.srv.frames(mark), _STOP_REQ)) == 1


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a13_stop_op_without_echo_is_not_reported_confirmed(kind: str) -> None:
    with _v2() as rig:
        rig.sim.frozen.set()  # робот не отвечает эхом
        _drop_seen_by_telemetry(rig, kind)
        reply = rig.call("stop", {"level": "SOFT"})
        assert reply.get("echo") is not True, reply


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a13_request_stop_without_echo_is_marked_unconfirmed(kind: str) -> None:
    with _v2() as rig:
        rig.sim.frozen.set()
        _drop_seen_by_telemetry(rig, kind)
        run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
        assert rig.drv.stop_unconfirmed is True


# --------------------------------------------------------------------------------------------------
# A14: стоп ленты через мост робота
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a14_vfd_stop_over_robot_bridge_after_drop_writes_two_frames(kind: str) -> None:
    with _v2() as rig:
        entry = DeviceEntry(
            id="vfd1",
            name="vfd1",
            kind="vfd",
            protocol="gd20_bridge",
            transport={"type": "bridge", "bridge": _DEV},
            params={},
        )
        vfd = VfdDriver(entry, None, resolve_device=lambda i: rig.drv if i == _DEV else None)
        assert run(vfd.connect) is True
        _drop_seen_by_telemetry(rig, kind)
        mark = rig.srv.mark()
        reply = run(lambda: vfd.call("stop", {}))
        time.sleep(0.3)
        frames = [f for f in rig.srv.frames(mark) if f.fc in (6, 16) and _overlaps(f, _VFD_FIRST, _VFD_LAST)]
        assert len(frames) == 2, (reply, frames)
        assert reply["status"] == "ok", reply


# --------------------------------------------------------------------------------------------------
# A15: робот v1 после обрыва не хуже main
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a15_v1_abort_arrives_and_link_recovers_after_drop(kind: str) -> None:
    sim = _Sim(RobotSimCore())
    drv = RobotDriver(_entry("rv1", "delta_universal3", sim.server.port, {"telemetry_interval_s": 0.0}))
    try:
        assert run(drv.connect, 30.0) is True
        drv.desired_connected = True
        run(lambda: drv.tick(None), 30.0)
        assert [f for f in sim.server.frames() if f.fc == 3] != [], "тик v1 не читает телеметрию"
        rule = sim.server.on_next(lambda f: f.fc == 3, kind)
        run(lambda: drv.tick(None), 30.0)
        assert rule.entered.is_set()

        mark = sim.server.mark()
        reply = run(lambda: drv.call("abort", {"mode": 3}), 30.0)
        time.sleep(0.3)
        stops = _writes_at(sim.server.frames(mark), _V1_REG_STOP)
        assert [f.values[0] for f in stops] == [3], (reply, stops)
        assert reply["status"] == "ok", reply

        mark = sim.server.mark()
        end = time.monotonic() + 20.0
        while not (drv.is_connected and [f for f in sim.server.frames(mark) if f.fc == 3]):
            assert time.monotonic() < end, "связь v1 не восстановилась за 20 с"
            run(lambda: drv.tick(None), 30.0)
            time.sleep(0.2)
        assert run(lambda: drv.call("abort", {"mode": 3}), 30.0)["status"] == "ok"
        assert sim.server.accepted >= 2
    finally:
        Call(drv.disconnect)._thread.join(10.0)
        sim.close()
    assert sim.errors == []
