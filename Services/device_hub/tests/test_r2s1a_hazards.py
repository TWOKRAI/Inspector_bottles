"""R2-S1a, часть 2: опасности автора (сеанс допуска и STOP после обрыва).

Настоящие ``RobotDriverV2``, ``ModbusDevice`` и pymodbus по TCP на ``127.0.0.1``; робот — ядро sim. Стенд
(сервер с обрывом, журнал кадров) — помощники слепой приёмки ``test_r2s1a_link_drop_acceptance``.

Что сторожится:
    - отказ по сеансу не оставляет метку команды «в полёте»;
    - отказ задания не закрывает уже новое соединение;
    - park и его шаг servo несут сеанс допуска, а не текущий;
    - ``param_apply`` после обрыва;
    - STOP при идущей программе, jog и задании (для задания порядок «запись STOP / ``_link_lost`` тика» навязан);
    - после штатного ``disconnect()`` повторный стоп молчит; связь, потерянную тиком, это не касается.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from Services.device_hub.tests.test_r2s1a_link_drop_acceptance import (
    _DRAW,
    _JOG_HOLD,
    _JOG_STEP,
    _Rig,
    _Ticker,
    _motion_writes,
    _v2,
    _wait,
    _writes_at,
)
from Services.modbus.core.device import ModbusDevice
from Services.modbus.tests.test_r2s1a_transport_acceptance import Call, run
from Services.robot_comm.robot_data import load_params
from Services.robot_comm.store import RobotDataStore

# Литералы протокола v2 (protocol-spec): ожидания не выводятся из проверяемого кода
_STOP_REQ = 0x1021
_CMD_SEQ = 0x1001
_OP_CVT_JOB = 32
_OP_SC_RUN = 48
_SOFT, _HARD = 1, 2
_TEXT_UNCONFIRMED = "стоп не подтверждён роботом"
_TEXT_DIVERGED = "параметр робота расходится с файлом"

_DEV = "rv2"
_JOB = {"x_mm": 300.0, "y_mm": 0.0, "e_capture": 0}
_RETURN = {"x_mm": 300.0, "y_mm": 0.0, "z_mm": -20.0}


def _drop(rig: _Rig, kind: str = "fin") -> None:
    rig.drop_seen_by_reader(kind)


def _drop_and_redial(rig: _Rig, kind: str = "fin") -> int:
    """Обрыв и тут же новое соединение (``on_error`` устройства). Возврат: сеанс нового соединения."""
    before = rig.drv.transport.session
    rig.redial.armed = True
    rig.drop_seen_by_reader(kind)
    assert rig.drv.transport.is_connected is True
    assert rig.drv.transport.session != before
    return rig.drv.transport.session


def _stop(rig: _Rig, how: str) -> None:
    if how == "request_stop":
        run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
    else:
        rig.drv.desired_connected = False  # как плагин: тик после disconnect не переподключает
        run(rig.drv.disconnect, 30.0)


def _stop_levels(rig: _Rig, mark: int) -> list[int]:
    return [f.values[0] & 3 for f in _writes_at(rig.srv.frames(mark), _STOP_REQ)]


def _op_writes(rig: _Rig, mark: int, opcode: int) -> int:
    return sum(1 for f in rig.srv.frames(mark) if f.fc == 16 and f.addr == _CMD_SEQ and f.values[1:2] == (opcode,))


def _tick_for(rig: _Rig, seconds: float) -> None:
    ticker = _Ticker(rig.drv)
    try:
        time.sleep(seconds)
    finally:
        ticker.close()


# --------------------------------------------------------------------------------------------------
# Отказ по сеансу — на провод ничего не ушло
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize(("op", "args"), [("jog_step", _JOG_STEP), ("jog_hold", _JOG_HOLD)], ids=["step", "hold"])
def test_refused_command_leaves_no_inflight_mark(op: str, args: dict, kind: str) -> None:
    with _v2(mode="fin-reconnected") as rig:
        mark, pending = rig.admitted_then_drop(lambda: rig.drv.call(op, dict(args)), kind)
        assert pending.value["status"] == "error", pending.value
        assert _motion_writes(rig.srv.frames(mark)) == []

        mark = rig.srv.mark()
        reply = rig.call(op, args)
        assert reply["status"] == "ok", reply  # с меткой «в полёте» здесь «Робот не ответил вовремя (этап response)»
        assert _motion_writes(rig.srv.frames(mark)) != []
        if op == "jog_hold":
            assert rig.call("jog_release")["status"] == "ok"


@pytest.mark.parametrize("mode", ["fin", "rst", "fin-reconnected"])
def test_param_apply_admitted_before_drop_is_refused(mode: str) -> None:
    with _v2(mode=mode) as rig:
        mark = rig.srv.mark()
        reply = rig.call("param_apply")
        assert reply["status"] == "ok", reply
        assert _motion_writes(rig.srv.frames(mark)) != []  # парная проверка: команда пишется

        mark, pending = rig.admitted_then_drop(lambda: rig.drv.call("param_apply", {}), mode.split("-")[0])
        time.sleep(0.3)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert pending.value["status"] == "error", pending.value

        rig.reconnect()
        mark = rig.srv.mark()
        reply = rig.call("param_apply")
        assert reply["status"] == "ok", reply
        assert _motion_writes(rig.srv.frames(mark)) != []


@pytest.mark.parametrize("mode", ["fin", "rst", "fin-reconnected"])
def test_param_set_admitted_before_drop_reports_no_divergence(tmp_path: Path, mode: str) -> None:
    """Запись значения не ушла: нет отката, нет «расходится с файлом», файл и метка прежние."""
    with _v2(tmp_path, mode=mode) as rig:
        store = RobotDataStore(tmp_path / "robot")
        args = {"name": "P_JOG_LEASE_MS", "value": 500.0, "base_rev": None}
        first = rig.call("param_set", args)
        assert first["status"] == "ok", first
        before = load_params(store, _DEV)

        args = {"name": "P_JOG_LEASE_MS", "value": 700.0, "base_rev": first["rev"]}
        published = len(rig.rec._items)
        mark, pending = rig.admitted_then_drop(lambda: rig.drv.call("param_set", args), mode.split("-")[0])
        time.sleep(0.3)
        assert pending.value["status"] == "error", pending.value
        assert _motion_writes(rig.srv.frames(mark)) == []
        errors = [p for path, p in list(rig.rec._items)[published:] if path.endswith(".last_error")]
        assert _TEXT_DIVERGED not in errors, errors
        assert errors == []
        assert load_params(store, _DEV) == before

        rig.reconnect()
        reply = rig.call("param_set", args)
        assert reply["status"] == "ok", reply
        # Метку здесь не сверяем: стенд не подключает param_source, и переподключение тиком (fin, rst) берёт метку из
        # умолчания, а не из файла. Неизменность метки отклонённой записи уже проверена равенством файла выше.
        assert load_params(store, _DEV).values["P_JOG_LEASE_MS"] == 700


@pytest.mark.parametrize("mode", ["fin", "fin-reconnected"])
def test_disabled_exchange_log_still_forwards_session(mode: str) -> None:
    """Выключенный журнал идёт отдельной веткой обёртки: сеанс допуска обязан пройти и по ней."""
    with _v2(mode=mode) as rig:
        assert rig.call("exchange_log_set", {"enabled": False})["status"] == "ok"
        mark, pending = rig.admitted_then_drop(lambda: rig.drv.call("jog_step", dict(_JOG_STEP)), "fin")
        time.sleep(0.5)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert pending.value["status"] == "error", pending.value


@pytest.mark.parametrize(
    ("op", "args", "counter"),
    [("enqueue_job", _JOB, "jobs_failed"), ("return_job", _RETURN, "returns_failed")],
    ids=["enqueue_job", "return_job"],
)
def test_queued_item_from_old_session_does_not_close_new_connection(op: str, args: dict, counter: str) -> None:
    """Связь поднята заново раньше тика: запись очереди отклонена, новое соединение остаётся."""
    with _v2(mode="fin-reconnected") as rig:
        assert rig.call(op, args)["status"] == "ok"
        session = _drop_and_redial(rig)
        mark = rig.srv.mark()
        _tick_for(rig, 2.0)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert rig.drv.snapshot()[counter] == 1
        assert rig.drv.is_connected is True
        assert rig.drv.transport.session == session

        mark = rig.srv.mark()
        assert rig.call(op, args)["status"] == "ok"
        ticker = _Ticker(rig.drv)
        try:
            _wait(lambda: _motion_writes(rig.srv.frames(mark)) != [], 15.0, "новая запись очереди на проводе")
        finally:
            ticker.close()


# --------------------------------------------------------------------------------------------------
# park: сеанс допуска хранится до шагов в тике
# --------------------------------------------------------------------------------------------------


def _park_states(rig: _Rig) -> list[str]:
    return [p["state"] for path, p in list(rig.rec._items) if path == f"devices.state.{_DEV}.park"]


def _park_to_the_end(rig: _Rig) -> None:
    done = _park_states(rig).count("done")
    assert rig.call("park")["status"] == "ok"
    ticker = _Ticker(rig.drv)
    try:
        _wait(lambda: _park_states(rig).count("done") > done, 40.0, "park done")
    finally:
        ticker.close()


def test_park_home_move_uses_session_of_admission() -> None:
    """Робот не дома: первая запись park — программа хода домой из потока исполнителя."""
    with _v2(mode="fin-reconnected") as rig:
        # свежий sim стоит дома: без этого шага park пропускает ход и тест проверял бы только SERVO
        assert rig.call("jog_step", {"dx": 20.0, "dy": 0.0, "spd": 20})["status"] == "ok"
        rig.wait_robot_idle()
        assert rig.call("park")["status"] == "ok"
        _drop_and_redial(rig)
        mark = rig.srv.mark()
        _tick_for(rig, 3.0)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert _park_states(rig)[-1] == "failed"

        mark = rig.srv.mark()
        _park_to_the_end(rig)  # парная проверка: новый park пишет и доходит
        assert _op_writes(rig, mark, _OP_SC_RUN) == 1  # ход домой действительно был


def test_park_servo_step_uses_session_of_admission() -> None:
    """Робот уже дома: единственная запись park — SERVO 0 из тика."""
    with _v2(mode="fin-reconnected") as rig:
        _park_to_the_end(rig)
        assert rig.call("servo", {"on": True})["status"] == "ok"
        rig.wait_robot_idle()

        assert rig.call("park")["status"] == "ok"
        _drop_and_redial(rig)
        mark = rig.srv.mark()
        _tick_for(rig, 3.0)
        assert _motion_writes(rig.srv.frames(mark)) == []
        assert _park_states(rig)[-1] == "failed"

        mark = rig.srv.mark()
        _park_to_the_end(rig)
        assert _motion_writes(rig.srv.frames(mark)) != []


# --------------------------------------------------------------------------------------------------
# STOP при идущей программе, jog и задании
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize(("how", "level"), [("request_stop", _HARD), ("disconnect", _SOFT)])
def test_stop_during_program_after_drop(tmp_path: Path, how: str, level: int, kind: str) -> None:
    points = [{"x_mm": 250.0 + 2.0 * i, "y_mm": 10.0 * (i % 2)} for i in range(60)]
    with _v2(tmp_path) as rig:
        reply = rig.call("draw_polyline", {**_DRAW, "points": points})
        assert reply["status"] == "ok", reply
        _wait(lambda: _op_writes(rig, 0, _OP_SC_RUN) >= 1, 20.0, "первый SC_RUN")
        mark = rig.srv.mark()
        _drop(rig, kind)
        _stop(rig, how)
        time.sleep(0.5)
        assert _stop_levels(rig, mark)[:1] == [level]


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("how", ["request_stop", "disconnect"])
def test_stop_after_drop_when_jog_lease_thread_is_gone(how: str, kind: str) -> None:
    """Поводок jog умер на обрыве раньше стопа: драйвер считает робота простым, STOP всё равно пишется."""
    with _v2() as rig:
        assert rig.call("jog_hold", _JOG_HOLD)["status"] == "ok"
        mark = rig.srv.mark()
        _drop(rig, kind)
        time.sleep(1.0)
        _stop(rig, how)
        time.sleep(0.5)
        assert _stop_levels(rig, mark)[:1] == [_SOFT]


_ORDER_WAIT_S = 10.0  # срок каждого принуждающего ожидания шва порядка


def _force_order(
    monkeypatch: pytest.MonkeyPatch, drv: object, order: str
) -> tuple[threading.Event, threading.Event, list[bool]]:
    """Шов теста: кто после обрыва первым берёт замок устройства — запись STOP или ``_link_lost`` тика.

    ``stop_first``: ``_link_lost`` тика не начинается, пока первая запись STOP не вернулась. ``tick_first``: первая
    запись STOP не идёт к замку устройства, пока ``_link_lost`` не отработал. Возврат: «поток стопа дошёл до записи
    STOP», «``_link_lost`` отработал», исходы принуждающих ожиданий (False — вышел срок, порядок не навязан).
    """
    stop_reached, stop_done, link_done = threading.Event(), threading.Event(), threading.Event()
    waits: list[bool] = []
    write = ModbusDevice.transaction
    link_lost: Callable[[], None] = drv._link_lost

    def ordered_write(device: ModbusDevice, ops: list[tuple], *, expected_session: int | None = None) -> bool:
        if stop_reached.is_set() or not any(op[1] == _STOP_REQ for op in ops):
            return write(device, ops, expected_session=expected_session)
        stop_reached.set()
        if order == "tick_first":
            waits.append(link_done.wait(_ORDER_WAIT_S))  # замок устройства ещё не взят
        try:
            return write(device, ops, expected_session=expected_session)
        finally:
            stop_done.set()

    def ordered_link_lost() -> None:
        if order == "stop_first" and not link_done.is_set():
            waits.append(stop_done.wait(_ORDER_WAIT_S))  # замок устройства достаётся записи STOP
        try:
            link_lost()
        finally:
            link_done.set()

    monkeypatch.setattr(ModbusDevice, "transaction", ordered_write)
    monkeypatch.setattr(drv, "_link_lost", ordered_link_lost)
    return stop_reached, link_done, waits


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("how", ["request_stop", "disconnect"])
@pytest.mark.parametrize("order", ["stop_first", "tick_first"])
def test_stop_during_job_after_drop(monkeypatch: pytest.MonkeyPatch, order: str, how: str, kind: str) -> None:
    """Обрыв пойман чтением самого тика, пока он ждёт задание; порядок на замке устройства задан параметром.

    ``tick_first`` — R2-S1d (ADR-DH-016): ``_link_lost`` не выбрасывает клиента SDK, STOP уходит и в этом порядке.
    """
    with _v2() as rig:
        assert rig.call("enqueue_job", _JOB)["status"] == "ok"
        ticker = _Ticker(rig.drv)
        try:
            _wait(lambda: _op_writes(rig, 0, _OP_CVT_JOB) == 1, 20.0, "CVT_JOB на проводе")
            rig.sim.frozen.set()  # задание не кончается
            held = rig.srv.on_next(lambda f: f.fc == 3, kind, hold=True)
            assert held.entered.wait(10.0), "тик не читает"
            stop_reached, link_done, waits = _force_order(monkeypatch, rig.drv, order)
            mark = rig.srv.mark()
            stopping = Call(lambda: _stop(rig, how))
            assert stop_reached.wait(_ORDER_WAIT_S), "стоп не дошёл до записи STOP_REQ"
            time.sleep(0.4)  # stop_first: запись STOP уже стоит в очереди на замок устройства
            held.release.set()
            stopping.result(30.0)
            assert link_done.wait(_ORDER_WAIT_S), "тик не дошёл до _link_lost"
            time.sleep(0.5)
            assert waits == [True]  # порядок навязан, а не вышел по сроку
            # R2-S1d: оба порядка — STOP на проводе (tick_first был [] до R2-S1d)
            assert _stop_levels(rig, mark) == [_HARD]
        finally:
            ticker.close()


# --------------------------------------------------------------------------------------------------
# Связь закрыта намеренно против связи, потерянной тиком
# --------------------------------------------------------------------------------------------------


def _quiet_stop_observed(rig: _Rig) -> tuple[list[int], bool, list[str], int]:
    """``request_stop`` и повторный ``disconnect``: (STOP, ``stop_unconfirmed``, новые ошибки, прирост tx_err)."""
    mark = rig.srv.mark()
    published = len(rig.rec._items)
    tx_err = rig.drv.snapshot()["stats"]["tx_err"]
    run(rig.drv.disconnect, 30.0)
    run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
    time.sleep(0.3)
    errors = [p for path, p in list(rig.rec._items)[published:] if path.endswith(".last_error")]
    return _stop_levels(rig, mark), rig.drv.stop_unconfirmed, errors, rig.drv.snapshot()["stats"]["tx_err"] - tx_err


@pytest.mark.parametrize("dropped_before", [False, True], ids=["healthy", "dropped"])
def test_stop_after_deliberate_disconnect_is_silent(dropped_before: bool) -> None:
    with _v2() as rig:
        if dropped_before:
            _drop(rig)
        rig.drv.desired_connected = False
        mark = rig.srv.mark()
        run(rig.drv.disconnect, 30.0)
        time.sleep(0.3)
        assert _stop_levels(rig, mark) == [_SOFT]  # сам disconnect стоп пишет — до закрытия
        assert _quiet_stop_observed(rig) == ([], False, [], 0)


@pytest.mark.parametrize("dropped_before", [False, True], ids=["healthy", "dropped"])
def test_operator_disconnect_button_still_writes_stop(dropped_before: bool) -> None:
    """«Отключить»: ``request_disconnect`` снимает ``desired_connected`` до ``disconnect()`` — STOP всё равно идёт."""
    with _v2() as rig:
        if dropped_before:
            _drop(rig)
        mark = rig.srv.mark()
        rig.drv.request_disconnect()
        run(rig.drv.disconnect, 30.0)
        time.sleep(0.3)
        assert _stop_levels(rig, mark) == [_SOFT]


def test_link_lost_by_tick_stop_is_on_the_wire() -> None:
    """R2-S1d (ADR-DH-016): связь, потерянную тиком, клиент SDK переживает — STOP уходит новым TCP, эхо есть.

    До R2-S1d здесь было «попытка без кадра и «стоп не подтверждён роботом»» (транспорт закрыт с обнулением клиента).
    """
    with _v2() as rig:
        rig.srv.on_next(lambda f: True, "fin")
        run(lambda: rig.drv.tick(None), 30.0)
        assert rig.drv.is_connected is False
        assert rig.drv.transport.is_connected is False
        mark, accepted, published = rig.srv.mark(), rig.srv.accepted, len(rig.rec._items)
        run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
        time.sleep(0.3)
        assert _stop_levels(rig, mark) == [_SOFT]
        assert rig.srv.accepted == accepted + 1
        assert rig.drv.stop_unconfirmed is False
        errors = [p for path, p in list(rig.rec._items)[published:] if path.endswith(".last_error")]
        assert _TEXT_UNCONFIRMED not in errors


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_reconnect_after_deliberate_disconnect_rearms_stop(kind: str) -> None:
    with _v2() as rig:
        rig.drv.desired_connected = False
        run(rig.drv.disconnect, 30.0)
        assert run(rig.drv.connect, 60.0) is True
        _drop(rig, kind)
        mark = rig.srv.mark()
        run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
        time.sleep(0.3)
        assert _stop_levels(rig, mark) == [_SOFT]


def test_disconnect_wanted_during_tick_reconnect_leaves_stop_silent() -> None:
    """«Хотим отключиться» пришло, пока тик переподключался: сокет закрывает хвост тика — тоже намеренно."""
    with _v2() as rig:
        rig.srv.on_next(lambda f: True, "fin")
        run(lambda: rig.drv.tick(None), 30.0)
        assert rig.drv.is_connected is False
        held = rig.srv.on_next(lambda f: f.fc == 3, "ok", hold=True)  # первое чтение пробы после переподключения
        ticker = _Ticker(rig.drv)
        try:
            assert held.entered.wait(20.0), "тик не переподключается"
            rig.drv.desired_connected = False
            held.release.set()
            _wait(lambda: rig.drv.transport.is_connected is False, 20.0, "тик закрыл сокет")
        finally:
            held.release.set()
            ticker.close()
        mark = rig.srv.mark()
        published = len(rig.rec._items)
        run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
        time.sleep(0.3)
        assert _stop_levels(rig, mark) == []
        assert rig.drv.stop_unconfirmed is False
        assert [p for path, p in list(rig.rec._items)[published:] if path.endswith(".last_error")] == []


# --------------------------------------------------------------------------------------------------
# disconnect: упавшая запись STOP повторяется один раз
# --------------------------------------------------------------------------------------------------


def _errors_since(rig: _Rig, published: int) -> list[str]:
    return [p for path, p in list(rig.rec._items)[published:] if path.endswith(".last_error")]


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_disconnect_stop_as_first_request_on_dead_link_is_retried(kind: str) -> None:
    with _v2() as rig:
        rig.srv.drop_idle(kind)
        mark = rig.srv.mark()
        published = len(rig.rec._items)
        _stop(rig, "disconnect")
        time.sleep(0.3)
        assert _stop_levels(rig, mark) == [_SOFT]
        assert rig.drv.stop_unconfirmed is False
        assert _errors_since(rig, published) == []


@pytest.mark.parametrize("prep", ["idle", "jog", "program"])
def test_disconnect_with_dead_host_says_unconfirmed_once_and_finishes(tmp_path: Path, prep: str) -> None:
    with _v2(tmp_path) as rig:
        if prep == "jog":
            assert rig.call("jog_hold", _JOG_HOLD)["status"] == "ok"
        if prep == "program":
            assert rig.call("draw_polyline", _DRAW)["status"] == "ok"
        mark = rig.srv.mark()
        published = len(rig.rec._items)
        rig.srv.close()  # хост пропал: ни старого соединения, ни нового
        started = time.monotonic()
        _stop(rig, "disconnect")  # run() держит срок 30 с: повтор не бесконечен
        print(f"DEAD_HOST {prep}: disconnect {time.monotonic() - started:.2f} с")
        assert _stop_levels(rig, mark) == []
        assert rig.drv.stop_unconfirmed is True
        assert _errors_since(rig, published).count(_TEXT_UNCONFIRMED) == 1
        assert rig.drv.is_connected is False

        published = len(rig.rec._items)
        run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
        assert _errors_since(rig, published) == []  # после законченного disconnect стоп ничего не добавляет
