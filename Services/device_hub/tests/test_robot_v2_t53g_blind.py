"""Слепая приёмка T5.3g: ``request_stop`` посреди ``connect`` не даёт драйверу стать «готовым» после выключения.

Purpose:
    Поведение снаружи (A1-A5 листа ``plans/robot-protocol-v2/tasks/T5.3g.blind-tester.md``): простой робот с
    подключённым транспортом получает ровно один SOFT за выключение, где бы ни застал стоп ``connect`` (внутри
    ``probe``, ``sync_params``, чтения TLM при подключении); готовый робот сохраняет «останавливается» и пометку
    «стоп не подтверждён»; не подключённый транспорт — ни записи, ни пометки; регресс A4/A5 как сейчас.
    Эффекты — то, что видит поддельный клиент (записи стопа с уровнем) и ответы публичного API; ожидаемые значения —
    литералы приёмки, не выводятся из кода драйвера.

Public API:
    Только тесты ``test_*``.

Stability: lite

Шов барьера: ``Event`` «вошли» + ``Event`` «отпустить», пауза ПОСЛЕ возврата охраняемого вызова и только в потоке
``connect``. Поток ``connect`` — daemon, ``join`` с дедлайном. Не вошли в точку — тест падает сообщением о
достижимости (отсутствие записей без этой проверки ничего не доказывает).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.errors import RobotAborted, RobotTimeout
from Services.robot_comm.programs import Move, Point, Program

_SOFT = 1  # STOP_LEVEL SOFT (protocol-spec §8)
_HARD = 2  # STOP_LEVEL HARD
_TEXT_STOPPING = "драйвер робота останавливается"
_TEXT_STOP_UNCONFIRMED = "стоп не подтверждён роботом"
_ERR_STOPPING = {"status": "error", "message": _TEXT_STOPPING}
_JOG = {"dir": 1, "spd": 20}
_PICK = {"x_mm": 300.0, "y_mm": -250.0}

_STOP_DEADLINE_S = 5.0  # срок request_stop: больше бюджета записи фейка (2 с), иначе TEXT_NO_ECHO_WINDOW
_ENTER_S = 10.0  # ждём вход connect в точку барьера
_HOLD_S = 30.0  # потолок удержания барьера (страховка от зависания; отпускает тест или teardown)
_STOP_JOIN_S = 8.0  # request_stop обязан вернуться, пока connect стоит на барьере
_JOIN_S = 15.0
_CALL_S = 15.0
_SCOPE_BUDGET_S = 6.0


# --------------------------------------------------------------------------------------------------
# обвязка: фейки и барьер
# --------------------------------------------------------------------------------------------------


class _Gate:
    """Барьер в одной точке: пауза после возврата охраняемого вызова, только в потоке ``connect``, один раз."""

    def __init__(self) -> None:
        self.point: str | None = None
        self.ident: int | None = None
        self.entered = threading.Event()
        self.release = threading.Event()

    def arm(self, point: str) -> None:
        self.point = point

    def hit(self, point: str) -> None:
        if self.point != point or threading.get_ident() != self.ident:
            return
        self.point = None  # одноразовый: повторный заход того же потока не держится
        self.entered.set()
        self.release.wait(_HOLD_S)


def _free_tlm() -> list[int]:
    """Блок TLM (32 слова от TLM_PROTO_VER): серво включено, захват свободен, метка параметров 1, энкодер 0."""
    base = REG["TLM_PROTO_VER"]
    words = [0] * 32
    words[REG["TLM_SERVO"] - base] = 1
    words[REG["TLM_CFG_EPOCH"] - base] = 1
    return words


class _Transport:
    def __init__(self, gate: _Gate, *, connected: bool) -> None:
        self.gate = gate
        self.is_connected = connected
        self.tlm = _free_tlm()

    def connect(self) -> bool:
        self.is_connected = True  # как настоящий транспорт: подключён до возврата
        self.gate.hit("transport")
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def read_registers(self, _address: int, _count: int) -> list[int]:
        result = list(self.tlm)
        self.gate.hit("read")
        return result


class _Client:
    """Клиент v2 на границе драйвера. ``stops`` — уровни записей STOP_REQ; эха нет (``await_stop_echo`` -> таймаут)."""

    heartbeat_period_s = None
    jog_lease_period_s = None

    def __init__(self, gate: _Gate) -> None:
        self.gate = gate
        self.stops: list[int] = []
        self.probes = 0
        self.jog_conts: list[tuple] = []
        self.cvt: list[tuple] = []
        self.wait: Callable[[Callable[[Any], None] | None], None] = lambda _poll: None
        self.stopped = threading.Event()

    def probe(self) -> None:
        self.probes += 1
        self.gate.hit("probe")

    def sync_params(self, _values: Any, _epoch: int, *, cancelled: Any = None) -> None:
        self.gate.hit("sync")

    def kick_heartbeat(self) -> None:
        pass

    def poll_errors(self) -> list:
        return []

    def jog_cont(self, *args: Any) -> Any:
        self.jog_conts.append(args)
        return type("Res", (), {"seq": len(self.jog_conts)})()

    def cvt_job(self, *args: Any) -> Any:
        self.cvt.append(args)
        return type("Res", (), {"seq": len(self.cvt)})()

    def wait_done(self, _seq: int, *, on_poll: Callable[[Any], None] | None = None) -> None:
        self.wait(on_poll)

    def stop(self, level: int) -> None:
        self.stops.append(level)
        self.stopped.set()

    def issue_stop(self, level: int) -> int:
        self.stop(level)
        return len(self.stops) * 4 + level

    def await_stop_echo(self, _value: int, _level: int, *, deadline: float) -> None:
        raise RobotTimeout("stop_echo")  # эхо стопа не приходит

    def run_chunks(self, _scenario: Any, *, params: Any, on_progress: Any) -> None:
        pass


class _Rig:
    def __init__(self, drv: RobotDriverV2, client: _Client, transport: _Transport, gate: _Gate) -> None:
        self.drv = drv
        self.client = client
        self.transport = transport
        self.gate = gate


@pytest.fixture
def make_rig() -> Iterator[Callable[..., _Rig]]:
    scope = open_scope("rv2t53g", budget_s=_SCOPE_BUDGET_S)
    made: list[_Rig] = []

    def make(*, transport_connected: bool = True) -> _Rig:
        gate = _Gate()
        entry = DeviceEntry(
            id="rv2",
            name="rv2",
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": 1, "unit_id": ROBOT_UNIT_ID},
            params={},
        )
        transport = _Transport(gate, connected=transport_connected)
        client = _Client(gate)
        drv = RobotDriverV2(
            entry,
            None,
            transport=transport,
            publish=lambda _p, _v: None,
            spawn=scope.spawn,
            client_factory=lambda _t, _c: client,  # шов: клиент v2 без sim
        )
        rig = _Rig(drv, client, transport, gate)
        made.append(rig)
        return rig

    try:
        yield make
    finally:
        for rig in made:
            rig.gate.release.set()
            rig.client.stopped.set()
            try:
                _bounded(rig.drv.disconnect, _CALL_S)
            except BaseException:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


def _bounded(fn: Callable[[], Any], deadline_s: float = _CALL_S) -> Any:
    """Вызов в daemon-потоке с дедлайном ``join``: зависший драйвер даёт красный тест, а не зависание."""
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается в поток теста
            box["error"] = exc

    thread = threading.Thread(target=runner, name="t53g-bounded", daemon=True)
    thread.start()
    thread.join(deadline_s)
    if thread.is_alive():
        raise AssertionError(f"вызов завис дольше {deadline_s} с")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _ready(rig: _Rig) -> None:
    """Готовый робот: обычный ``connect`` без барьера вернул True."""
    assert _bounded(rig.drv.connect) is True, "первый connect не дал готового робота (настройка теста)"


def _connect_with_stop_at(rig: _Rig, point: str) -> bool:
    """``connect`` в daemon-потоке; в точке ``point`` он стоит, из потока теста идёт ``request_stop``; затем отпуск.

    Не вошли в точку — падение с сообщением о достижимости. ``request_stop`` обязан вернуться, пока ``connect``
    стоит на барьере. Возвращает результат ``connect``.
    """
    gate = rig.gate
    box: dict[str, Any] = {}

    def run_connect() -> None:
        gate.ident = threading.get_ident()
        try:
            box["result"] = rig.drv.connect()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    gate.arm(point)
    connect_thread = threading.Thread(target=run_connect, name="t53g-connect", daemon=True)
    connect_thread.start()
    stop_box: dict[str, Any] = {}
    try:
        started = time.monotonic()
        while not gate.entered.wait(0.05):
            if not connect_thread.is_alive() or time.monotonic() - started > _ENTER_S:
                break
        if not gate.entered.is_set():
            pytest.fail(
                f"достижимость: connect не дошёл до точки {point!r} "
                f"(поток жив: {connect_thread.is_alive()}, результат: {box}) — окно не проверено"
            )

        def run_stop() -> None:
            try:
                rig.drv.request_stop(time.monotonic() + _STOP_DEADLINE_S)
            except BaseException as exc:  # noqa: BLE001
                stop_box["error"] = exc

        stop_thread = threading.Thread(target=run_stop, name="t53g-request-stop", daemon=True)
        stop_thread.start()
        stop_thread.join(_STOP_JOIN_S)
        stop_blocked = stop_thread.is_alive()
    finally:
        gate.release.set()
    connect_thread.join(_JOIN_S)
    assert not connect_thread.is_alive(), f"connect не вернулся за {_JOIN_S} с после отпуска барьера {point!r}"
    assert not stop_blocked, f"request_stop не вернулся за {_STOP_JOIN_S} с, пока connect стоял в точке {point!r}"
    assert "error" not in stop_box, f"request_stop бросил: {stop_box['error']!r}"
    assert "error" not in box, f"connect бросил: {box['error']!r}"
    return box["result"]


def _a1_observed(rig: _Rig, result: bool) -> dict[str, Any]:
    return {
        "stops": list(rig.client.stops),
        "connect": result,
        "is_connected": bool(rig.drv.is_connected),
        "is_shutdown": rig.drv.state.is_shutdown(),
    }


_A1_EXPECTED = {"stops": [_SOFT], "connect": False, "is_connected": False, "is_shutdown": True}


# --------------------------------------------------------------------------------------------------
# A1: простой робот, транспорт подключён, стоп в точке connect -> ровно 1 SOFT, не «готов»
# --------------------------------------------------------------------------------------------------


def test_a1_stop_inside_probe_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    result = _connect_with_stop_at(rig, "probe")
    assert _a1_observed(rig, result) == _A1_EXPECTED


def test_a1_stop_inside_sync_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    result = _connect_with_stop_at(rig, "sync")
    assert _a1_observed(rig, result) == _A1_EXPECTED


def test_a1_stop_inside_on_connect_read_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    result = _connect_with_stop_at(rig, "read")
    assert _a1_observed(rig, result) == _A1_EXPECTED


def test_a1_stop_before_connect_on_ready_robot(make_rig: Callable[..., _Rig]) -> None:
    """Готовый робот: ``request_stop``, затем ``connect`` -> 1 SOFT, ``connect`` False (``is_connected`` не смотрим)."""
    rig = make_rig()
    _ready(rig)
    _bounded(lambda: rig.drv.request_stop(time.monotonic() + _STOP_DEADLINE_S))
    result = _bounded(rig.drv.connect)
    assert {"stops": list(rig.client.stops), "connect": result} == {"stops": [_SOFT], "connect": False}


# --------------------------------------------------------------------------------------------------
# A2: готовый робот, стоп внутри probe повторного connect: «останавливается» и «не подтверждён» живут
# --------------------------------------------------------------------------------------------------


def test_a2_ready_robot_stop_inside_probe_keeps_stopping(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    _ready(rig)
    rig.client.probes = 0
    result = _connect_with_stop_at(rig, "probe")
    program = Program(name="t53g", steps=(Move(point="a", kind="JOINT"),))
    points = {"a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1)}
    observed = {
        "connect": result,
        "is_connected": bool(rig.drv.is_connected),
        "stopping": rig.drv.state.view().stopping,
        "jog_hold": _bounded(lambda: rig.drv.call("jog_hold", dict(_JOG))),
        "start_program": _bounded(lambda: rig.drv.start_program(program, points, None, name="t53g")),
        "stop_unconfirmed": rig.drv.stop_unconfirmed,
        "stop_unconfirmed_text": rig.drv.stop_unconfirmed_text,
        "stops": list(rig.client.stops),
    }
    assert observed == {
        "connect": False,
        "is_connected": False,
        "stopping": True,
        "jog_hold": _ERR_STOPPING,
        "start_program": _ERR_STOPPING,
        "stop_unconfirmed": True,
        "stop_unconfirmed_text": _TEXT_STOP_UNCONFIRMED,
        "stops": [_SOFT],
    }
    assert rig.client.probes == 1, "повторный connect не дошёл до probe ровно один раз (настройка теста)"


# --------------------------------------------------------------------------------------------------
# A3: стоп, пока connect ещё подключает транспорт -> записи нет, пометки нет
# --------------------------------------------------------------------------------------------------


def test_a3_stop_inside_transport_connect_no_write(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(transport_connected=False)
    result = _connect_with_stop_at(
        rig, "transport"
    )  # вход в точку проверен внутри: без него 0 записей ничего не значит
    observed = {
        "stops": list(rig.client.stops),
        "stop_unconfirmed": rig.drv.stop_unconfirmed,
        "stop_unconfirmed_text": rig.drv.stop_unconfirmed_text,
        "connect": result,
        "is_shutdown": rig.drv.state.is_shutdown(),  # request_stop отработал (достижимость эффекта)
    }
    assert observed == {
        "stops": [],
        "stop_unconfirmed": False,
        "stop_unconfirmed_text": None,
        "connect": False,
        "is_shutdown": True,
    }


# --------------------------------------------------------------------------------------------------
# A4: регресс
# --------------------------------------------------------------------------------------------------


def test_a4_stop_after_connect_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    _ready(rig)
    _bounded(lambda: rig.drv.request_stop(time.monotonic() + _STOP_DEADLINE_S))
    assert list(rig.client.stops) == [_SOFT]


def test_a4_disconnect_then_connect_clears_stopping(make_rig: Callable[..., _Rig]) -> None:
    """``disconnect`` без ``request_stop``, затем ``connect`` снимает ``stopping`` («ручное Подключить»)."""
    rig = make_rig()
    _ready(rig)
    _bounded(rig.drv.disconnect)
    assert _bounded(rig.drv.connect) is True
    jog = _bounded(lambda: rig.drv.call("jog_hold", dict(_JOG)))
    observed = {"stopping": rig.drv.state.view().stopping, "jog_refused_as_stopping": jog == _ERR_STOPPING}
    assert observed == {"stopping": False, "jog_refused_as_stopping": False}, jog


# --------------------------------------------------------------------------------------------------
# A5: задание посреди connect — как сейчас: без probe, стоп HARD один раз, SOFT нет
# --------------------------------------------------------------------------------------------------


def test_a5_connect_during_job_no_new_writes(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    _ready(rig)
    client = rig.client
    entered = threading.Event()

    def wait(on_poll: Callable[[Any], None] | None) -> None:
        entered.set()
        while not client.stopped.wait(0.02):
            if on_poll is not None:
                on_poll(_free_tlm())
        raise RobotAborted(1, 13, "Прервано стопом")  # 13 — E_ABORTED (protocol-spec §6)

    client.wait = wait
    assert rig.drv.call("enqueue_job", dict(_PICK))["status"] == "ok"
    ticker = threading.Thread(target=lambda: rig.drv.tick(None), name="t53g-tick", daemon=True)
    ticker.start()
    try:
        assert entered.wait(10.0), "достижимость: тик не дошёл до wait_done — задание в полёте не создано"
        probes = client.probes
        result = _bounded(rig.drv.connect)
        writes_after_connect = list(client.stops)
        _bounded(lambda: rig.drv.request_stop(time.monotonic() + _STOP_DEADLINE_S))
        observed = {
            "connect": result,
            "probes_added": client.probes - probes,
            "stops_after_connect": writes_after_connect,
            "stops_after_request_stop": list(client.stops),
        }
    finally:
        client.stopped.set()
        ticker.join(_JOIN_S)
    assert not ticker.is_alive(), "тик не вышел после стопа"
    assert observed == {
        "connect": True,
        "probes_added": 0,
        "stops_after_connect": [],
        "stops_after_request_stop": [_HARD],
    }
