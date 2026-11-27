"""R2-S1d: опасности автора — СТОП оператора не запирается готовностью (ADR-DH-016).

Настоящие ``RobotDriverV2``, ``ModbusDevice`` и pymodbus по TCP на ``127.0.0.1``; робот — ядро sim v2 (стенд R2-S1a).
Порядок потоков задаётся входом теста (шов на ``ModbusDevice.connect`` / ``ModbusSdkClient.connect``), не удачей
планировщика; блокирующиеся вызовы — в потоках-демонах со сроком (``Call`` / ``run``).

Что сторожится:
    - СТОП в окне между закрытием и открытием транспорта — в ``connect`` и после ``_link_lost`` (обе точки driver.py);
    - ``drop_link`` против последующих ``connect`` / ``disconnect``: клиент SDK жив, после намеренного — СТОП молчит;
    - нажатие во время идущего connect тика на мёртвом хосте: срок ответа (число в ``MEASURE:``);
    - повтор записи СТОПа оператора — ровно один и только по причине «встроенный ``ConnectionError``»;
    - ``stop_unconfirmed`` переживает неудачный connect;
    - ``ExchangeLogTransport.drop_link``: проброс внутреннему и откат на ``disconnect`` у дублёра.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from pymodbus.exceptions import ConnectionException, ModbusIOException

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.exchange_log import ExchangeLog, ExchangeLogTransport
from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.drivers.robot_driver_v2.state import RobotState
from Services.device_hub.tests.test_r2s1a_hazards import _errors_since, _stop_levels
from Services.device_hub.tests.test_r2s1a_link_drop_acceptance import _Rec, _Rig, _Sim, _Ticker, _entry, _v2
from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk.client import ModbusSdkClient
from Services.modbus.sdk.errors import ModbusConnectionError, ModbusIOError
from Services.modbus.tests.test_r2s1a_transport_acceptance import Call, run
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.client_v2 import RobotClientV2
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

# Литералы протокола и спецификации: ожидания не выводятся из проверяемого кода
_HARD = 2
_STOP_HARD = {"level": "HARD"}
_TEXT_UNCONFIRMED = "стоп не подтверждён роботом"


def _stop(rig: _Rig) -> tuple[dict, float]:
    started = time.monotonic()
    reply = rig.call("stop", _STOP_HARD)
    return reply, time.monotonic() - started


# --------------------------------------------------------------------------------------------------
# Окно «закрыт — не открыт»: connect драйвера
# --------------------------------------------------------------------------------------------------


def test_stop_between_drop_and_open_in_connect_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    with _v2() as rig:
        rig.drv.state.set_ready(False)  # как после неудачного connect: транспорт открыт, драйвер не готов
        assert rig.drv.transport.is_connected is True
        entered, release = threading.Event(), threading.Event()
        waits: list[bool] = []
        original = ModbusDevice.connect

        def gated(device: ModbusDevice) -> bool:
            if not entered.is_set():
                entered.set()
                waits.append(release.wait(10.0))  # замок устройства не взят
            return original(device)

        monkeypatch.setattr(ModbusDevice, "connect", gated)
        accepted = rig.srv.accepted
        connecting = Call(rig.drv.connect)
        try:
            assert entered.wait(10.0), "connect не дошёл до открытия транспорта"
            assert rig.drv.transport.is_connected is False, "предпосылка: сокет закрыт, ещё не открыт"
            mark = rig.srv.mark()
            reply, elapsed = _stop(rig)
            print(f"MEASURE: СТОП в окне connect: {elapsed:.3f} с, {reply}")
            assert waits == [], "СТОП должен пройти, пока окно открыто"
            assert reply["status"] == "ok", reply
            assert _stop_levels(rig, mark) == [_HARD]
            assert rig.srv.accepted == accepted + 1  # новый TCP неявным connect pymodbus
        finally:
            release.set()
        assert connecting.result(60.0) is True
        assert waits == [True]


# --------------------------------------------------------------------------------------------------
# Окно «закрыт — не открыт»: _link_lost тика; затем connect и намеренный disconnect
# --------------------------------------------------------------------------------------------------


def test_stop_after_link_lost_then_connect_then_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    with _v2() as rig:
        accepted = rig.srv.accepted
        failed: list[bool] = []
        original = RobotClientV2.kick_heartbeat

        def raw_failure(client: RobotClientV2) -> None:
            if not failed:
                failed.append(True)
                raise OSError("сырой сбой сокета мимо ModbusDevice")  # транспорт остаётся «подключённым»
            original(client)

        monkeypatch.setattr(RobotClientV2, "kick_heartbeat", raw_failure)
        assert rig.drv.transport.is_connected is True
        run(lambda: rig.drv.tick(None), 20.0)  # тик: пульс упал -> _link_lost снимает связь
        assert failed == [True]
        assert rig.drv.transport.is_connected is False
        assert rig.drv.is_connected is False

        mark = rig.srv.mark()
        reply, _ = _stop(rig)
        assert reply["status"] == "ok", reply
        assert _stop_levels(rig, mark) == [_HARD]
        assert rig.srv.accepted == accepted + 1

        session = rig.drv.transport.session
        assert run(rig.drv.connect, 60.0) is True  # клиент SDK тот же: connect работает как раньше
        assert rig.drv.transport.session > session
        rig.drv.desired_connected = False
        run(rig.drv.disconnect, 30.0)

        mark, accepted = rig.srv.mark(), rig.srv.accepted
        reply, _ = _stop(rig)
        assert reply["status"] == "error", reply
        assert reply["message"] and reply["error"], reply
        time.sleep(0.3)
        assert _stop_levels(rig, mark) == []
        assert rig.srv.accepted == accepted


# --------------------------------------------------------------------------------------------------
# Нажатие во время идущего connect тика (мёртвый хост)
# --------------------------------------------------------------------------------------------------


@contextmanager
def _fast_rig(timeout_s: float) -> Iterator[_Rig]:
    """Стенд ``_v2`` с транспортом ``timeout_sec=timeout_s``, ``retries=1``."""
    sim = _Sim(RobotSimCoreV2())
    scope = open_scope("r2s1d", budget_s=6.0)
    rec = _Rec()
    drv = None
    try:
        config = ModbusConfig(host="127.0.0.1", port=sim.server.port, unit_id=2, timeout_sec=timeout_s, retries=1)
        entry = _entry("rv2", "delta_v2", sim.server.port)
        drv = RobotDriverV2(entry, None, publish=rec, spawn=scope.spawn, transport=ModbusDevice(config))
        assert run(drv.connect, 60.0) is True
        drv.desired_connected = True
        yield _Rig(sim, drv, rec)
        assert sim.errors == [], f"ядро sim упало: {sim.errors}"
    finally:
        if drv is not None:
            drv.desired_connected = False
            Call(drv.disconnect).join(20.0)
        scope.close()
        sim.close()


def test_press_during_tick_connect_on_dead_host(monkeypatch: pytest.MonkeyPatch) -> None:
    with _fast_rig(timeout_s=1.0) as rig:
        in_connect = threading.Event()
        original = ModbusSdkClient.connect

        def watched(client: ModbusSdkClient) -> bool:
            in_connect.set()  # ModbusDevice.connect уже держит замок устройства
            return original(client)

        rig.srv.close()  # порт закрыт: тик замечает обрыв и переподключается к мёртвому хосту
        monkeypatch.setattr(ModbusSdkClient, "connect", watched)
        ticker = _Ticker(rig.drv)
        try:
            assert in_connect.wait(15.0), "тик не начал переподключение"
            published = len(rig.rec._items)
            reply, elapsed = _stop(rig)
            print(f"MEASURE: нажатие во время connect тика (timeout_sec=1.0, retries=1): {elapsed:.3f} с, {reply}")
            assert reply["status"] == "error", reply
            assert reply["message"] and reply["error"], reply
            assert elapsed < 3.0
            time.sleep(0.3)
            assert _errors_since(rig, published).count(_TEXT_UNCONFIRMED) == 1
            assert rig.drv.stop_unconfirmed is True
        finally:
            ticker.close()


# --------------------------------------------------------------------------------------------------
# Повтор записи СТОПа оператора: ровно один и только на мёртвом сокете
# --------------------------------------------------------------------------------------------------


def _write_error(cause: str) -> Exception:
    """Первая ошибка записи STOP, как её отдаёт ``ModbusDevice`` (``ModbusIOError ... from <причина>``)."""
    causes: dict[str, BaseException | None] = {
        "reset": ConnectionResetError(10054, "удалённый хост разорвал соединение"),
        "aborted": ConnectionAbortedError(10053, "соединение прервано"),
        "broken_pipe": BrokenPipeError(32, "broken pipe"),
        "pymodbus_timeout": ModbusIOException("No response received"),
        "pymodbus_connect": ConnectionException("Failed to connect"),
        "no_cause": None,
    }
    if cause == "session":
        return ModbusConnectionError("сеанс связи сменился")
    try:
        raise ModbusIOError("write_register -> ошибка обмена") from causes[cause]
    except ModbusIOError as exc:
        return exc


@pytest.mark.parametrize(
    ("cause", "attempts", "status", "frames", "unconfirmed"),
    [
        ("reset", 2, "ok", [_HARD], 0),
        ("aborted", 2, "ok", [_HARD], 0),
        ("broken_pipe", 2, "ok", [_HARD], 0),
        ("pymodbus_timeout", 1, "error", [], 1),
        ("pymodbus_connect", 1, "error", [], 1),
        ("no_cause", 1, "error", [], 1),
        ("session", 1, "error", [], 1),
    ],
)
def test_operator_stop_retries_once_only_on_builtin_connection_error(
    monkeypatch: pytest.MonkeyPatch, cause: str, attempts: int, status: str, frames: list[int], unconfirmed: int
) -> None:
    with _v2() as rig:
        real = RobotClientV2.issue_stop
        calls: list[int] = []

        def first_fails(client: RobotClientV2, level: int) -> int:
            calls.append(level)
            if len(calls) == 1:
                raise _write_error(cause)
            return real(client, level)

        monkeypatch.setattr(RobotClientV2, "issue_stop", first_fails)
        mark, published = rig.srv.mark(), len(rig.rec._items)
        reply, _ = _stop(rig)
        time.sleep(0.2)
        assert len(calls) == attempts
        assert reply["status"] == status, reply
        if status == "error":
            assert reply["message"] and reply["error"], reply
        assert _stop_levels(rig, mark) == frames
        assert _errors_since(rig, published).count(_TEXT_UNCONFIRMED) == unconfirmed


def test_operator_stop_both_writes_failed_publishes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    with _v2() as rig:
        calls: list[int] = []

        def always_dead(_client: RobotClientV2, level: int) -> int:
            calls.append(level)
            raise _write_error("reset")

        monkeypatch.setattr(RobotClientV2, "issue_stop", always_dead)
        published = len(rig.rec._items)
        reply, _ = _stop(rig)
        assert reply["status"] == "error", reply
        assert len(calls) == 2
        assert _errors_since(rig, published).count(_TEXT_UNCONFIRMED) == 1
        assert rig.drv.stop_unconfirmed is True


# --------------------------------------------------------------------------------------------------
# stop_unconfirmed переживает неудачный connect
# --------------------------------------------------------------------------------------------------


def test_stop_unconfirmed_survives_failed_connect() -> None:
    state = RobotState(clock=time.monotonic, queue_maxlen=8)
    state.mark_unconfirmed(_TEXT_UNCONFIRMED)
    assert state.connect_begin() == ("go", False)
    state.connect_end()  # connect не удался: до connect_finish не дошёл
    assert state.stop_unconfirmed() is True
    assert state.connect_begin() == ("go", False)
    assert state.connect_finish() is True
    state.connect_end()
    assert state.stop_unconfirmed() is False
    state.mark_unconfirmed(_TEXT_UNCONFIRMED)
    state.connect_reset()
    assert state.stop_unconfirmed() is False


# --------------------------------------------------------------------------------------------------
# ExchangeLogTransport.drop_link
# --------------------------------------------------------------------------------------------------


class _Inner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.is_connected = True

    def disconnect(self) -> None:
        self.calls.append("disconnect")


class _InnerWithDrop(_Inner):
    def drop_link(self) -> None:
        self.calls.append("drop_link")


@pytest.mark.parametrize("enabled", [True, False], ids=["log_on", "log_off"])
@pytest.mark.parametrize(("inner_cls", "expected"), [(_InnerWithDrop, ["drop_link"]), (_Inner, ["disconnect"])])
def test_exchange_log_transport_drop_link_forwards_or_falls_back(
    enabled: bool, inner_cls: type, expected: list
) -> None:
    inner: Any = inner_cls()
    wrapper = ExchangeLogTransport(inner, ExchangeLog("rv2", enabled=enabled))
    wrapper.drop_link()
    assert inner.calls == expected


# --------------------------------------------------------------------------------------------------
# v1 abort без связи (решение лида 2026-11-27, вариант c'): одна попытка записи, неудача — прежний отказ
# --------------------------------------------------------------------------------------------------

_TEXT_NOT_CONNECTED_RV1 = "Устройство 'rv1' не подключено"


@contextmanager
def _v1(*, timeout_s: float = 1.0, connect: bool = True) -> Iterator[tuple[_Sim, RobotDriver]]:
    sim = _Sim(RobotSimCore())
    entry = DeviceEntry(
        id="rv1",
        name="rv1",
        kind="robot",
        protocol="delta_universal3",
        transport={
            "type": "tcp",
            "host": "127.0.0.1",
            "port": sim.server.port,
            "unit_id": 2,
            "timeout_sec": timeout_s,
            "retries": 1,
        },
        params={"telemetry_interval_s": 0.0},
    )
    drv = RobotDriver(entry)
    try:
        if connect:
            assert run(drv.connect, 30.0) is True
            drv.desired_connected = True
        yield sim, drv
    finally:
        Call(drv.disconnect).join(10.0)
        sim.close()


def _v1_abort(drv: RobotDriver, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, float, list[int]]:
    """``call("abort", {mode: 3})``: ответ, длительность, режимы каждой попытки записи клиента v1."""
    attempts: list[int] = []
    original = RobotClient.stop

    def counted(client: RobotClient, mode: int) -> bool:
        attempts.append(mode)
        return original(client, mode)

    monkeypatch.setattr(RobotClient, "stop", counted)
    started = time.monotonic()
    reply = run(lambda: drv.call("abort", {"mode": 3}), 30.0)
    return reply, time.monotonic() - started, attempts


@pytest.mark.parametrize(
    ("state", "attempts", "accepted"),
    [("never_connected", [], 0), ("deliberate_disconnect", [3], 1)],
)
def test_v1_abort_without_link_after_deliberate_close_has_no_frame_and_no_tcp(
    monkeypatch: pytest.MonkeyPatch, state: str, attempts: list[int], accepted: int
) -> None:
    with _v1(connect=state != "never_connected") as (sim, drv):
        if state == "deliberate_disconnect":
            drv.desired_connected = False
            run(drv.disconnect, 30.0)
        mark = sim.server.mark()
        reply, _, tried = _v1_abort(drv, monkeypatch)
        time.sleep(0.3)
        assert reply["status"] == "error", reply
        assert reply["message"] == _TEXT_NOT_CONNECTED_RV1
        assert reply["error"].startswith(_TEXT_NOT_CONNECTED_RV1), reply
        assert tried == attempts
        assert sim.server.frames(mark) == []
        assert sim.server.accepted == accepted


def test_v1_abort_on_dead_host_one_attempt_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    with _v1(timeout_s=1.0) as (sim, drv):
        sim.server.close()  # порт закрыт: тик замечает обрыв, переподключиться некуда
        end = time.monotonic() + 15.0
        while drv.is_connected:
            assert time.monotonic() < end, "тик v1 не заметил обрыв за 15 с"
            run(lambda: drv.tick(None), 30.0)
            time.sleep(0.2)
        reply, elapsed, tried = _v1_abort(drv, monkeypatch)
        print(f"MEASURE: v1 abort на мёртвом хосте (timeout_sec=1.0, retries=1): {elapsed:.3f} с, {reply}")
        assert reply["status"] == "error", reply
        assert reply["message"] == _TEXT_NOT_CONNECTED_RV1
        assert reply["error"] != reply["message"], "в error нет причины"
        assert tried == [3]  # ровно одна попытка, без повтора
