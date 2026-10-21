"""Слепая приёмка T5.3h: обычный «Отключить» посреди ``connect`` у простого робота даёт ровно один стоп SOFT.

Purpose:
    Решение владельца 2026-10-21: простой робот (нет задания, программы, jog), которому ``disconnect()`` пришёл
    посреди ``connect`` ПОСЛЕ подъёма связи, получает ровно одну запись стопа уровня SOFT (1); ДО подъёма связи
    (внутри ``transport.connect()`` или при закрытии старого сокета) записи нет. Тесты ставят паузу в одной
    точке ``connect`` (фейковые клиент и транспорт), зовут ``disconnect()`` из другого потока и считают записи
    стопа, записанные фейковым клиентом.

Public API:
    Только тесты ``test_*``.

Stability: lite

Источник приёмки — ``plans/robot-protocol-v2/tasks/T5.3h.blind-tester.md`` (писался без чтения реализации).
Допущения тестера:
    * уровень SOFT протокола v2 — 1, запись стопа видна как вызов ``client.stop(level)`` / ``client.issue_stop``;
    * «окно» (точка паузы) достижимо из потока ``connect`` — это проверяется отдельно, до проверки результата;
      недостижимое окно — красный тест с пометкой «окно недостижимо», а не молчаливая зелень «0 записей»;
    * ``disconnect()`` может ждать конца ``connect`` — тест не требует, чтобы он вернулся до отпускания паузы.
Каждый блокирующий вызов идёт в daemon-потоке с дедлайном ``join``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.registers import ROBOT_UNIT_ID

_SOFT = 1  # STOP_LEVEL SOFT протокола v2
_STOPPING_TEXT = "останавливается"  # из «драйвер робота останавливается»
_JOG = {"dir": 1, "spd": 20}

_FIRST_DEADLINE_S = 1.0  # первый тест файла: короткий дедлайн
_DEADLINE_S = 5.0
_GATE_HOLD_S = 10.0  # пауза в точке сама отпускается: брошенный поток не висит вечно
_DISC_PROBE_S = 1.0  # сколько ждём возврата disconnect при удержанной паузе (он вправе ждать connect)
_SCOPE_BUDGET_S = 6.0


@pytest.fixture
def driver_scope() -> Iterator[Any]:
    scope = open_scope("rv2t53h", budget_s=_SCOPE_BUDGET_S)
    try:
        yield scope
    finally:
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


class _Gate:
    """Пауза в точке: первый вызов запоминает поток, ставит ``entered`` и ждёт ``release``; прочие проходят."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._fired = False

    def hit(self) -> None:
        with self._lock:
            if self._fired:
                return
            self._fired = True
            self.thread = threading.current_thread()
        self.entered.set()
        self.release.wait(_GATE_HOLD_S)


def _free_tlm() -> list[int]:
    from Services.robot_comm.core.protocol_v2 import REG

    base = REG["TLM_PROTO_VER"]
    words = [0] * 32
    words[REG["TLM_SERVO"] - base] = 1
    words[REG["TLM_CFG_EPOCH"] - base] = 1
    return words


class _FakeTransport:
    def __init__(self, connected: bool) -> None:
        self.is_connected = connected
        self.closed = 0
        self.hooks: dict[str, _Gate] = {}

    def connect(self) -> bool:
        self.is_connected = True  # как настоящий транспорт: связь поднята до возврата
        if (gate := self.hooks.get("connect")) is not None:
            gate.hit()
        return True

    def disconnect(self) -> None:
        self.closed += 1
        if (gate := self.hooks.get("disconnect")) is not None:
            gate.hit()
        self.is_connected = False

    def read_registers(self, _address: int, _count: int) -> list[int]:
        if (gate := self.hooks.get("read")) is not None:
            gate.hit()
        return _free_tlm()


class _FakeClient:
    heartbeat_period_s = None
    jog_lease_period_s = None

    def __init__(self) -> None:
        self.stops: list[int] = []
        self.probes = 0
        self.syncs = 0
        self.hooks: dict[str, _Gate] = {}
        self.other: list[str] = []

    def probe(self) -> None:
        self.probes += 1
        if (gate := self.hooks.get("probe")) is not None:
            gate.hit()

    def sync_params(self, _values: Any, _epoch: int, *, cancelled: Any = None) -> None:
        self.syncs += 1
        if (gate := self.hooks.get("sync")) is not None:
            gate.hit()

    def kick_heartbeat(self) -> None:
        pass

    def poll_errors(self) -> list:
        return []

    def stop(self, level: int) -> None:
        self.stops.append(level)

    def issue_stop(self, level: int) -> int:
        self.stop(level)
        return len(self.stops) * 4 + level

    def await_stop_echo(self, _value: int, _level: int, *, deadline: float) -> None:
        pass

    def __getattr__(self, name: str) -> Callable[..., None]:
        # прочие вызовы клиента (jog_cont и т.п.) — молчаливая запись; приватные имена не подменяем
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*_a: Any, **_k: Any) -> None:
            self.other.append(name)

        return call


@dataclass
class _Rig:
    drv: RobotDriverV2
    client: _FakeClient
    transport: _FakeTransport
    gates: list[_Gate] = field(default_factory=list)

    def gate(self, point: str) -> _Gate:
        """Поставить паузу в точку: probe / sync (клиент), connect / disconnect / read (транспорт)."""
        gate = _Gate()
        (self.client if point in ("probe", "sync") else self.transport).hooks[point] = gate
        self.gates.append(gate)
        return gate


@pytest.fixture
def make_rig(driver_scope: Any) -> Iterator[Callable[..., _Rig]]:
    rigs: list[_Rig] = []

    def factory(*, transport_connected: bool = True, **params: Any) -> _Rig:
        entry = DeviceEntry(
            id="rv2",
            name="rv2",
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": 1, "unit_id": ROBOT_UNIT_ID},
            params=params,
        )
        transport = _FakeTransport(transport_connected)
        drv = RobotDriverV2(entry, None, transport=transport, publish=lambda _p, _v: None, spawn=driver_scope.spawn)
        client = _FakeClient()
        drv._client = client  # шов: клиент v2 без sim (как во всех тестах драйвера)
        rig = _Rig(drv, client, transport)
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        for gate in rig.gates:
            gate.release.set()
        _call_bounded(rig.drv.disconnect, _DEADLINE_S, swallow=True)


@dataclass
class _Run:
    thread: threading.Thread
    result: list[Any] = field(default_factory=list)
    error: list[BaseException] = field(default_factory=list)

    def done(self) -> bool:
        return not self.thread.is_alive()


def _start(name: str, fn: Callable[[], Any]) -> _Run:
    holder: list[Any] = []
    errors: list[BaseException] = []

    def body() -> None:
        try:
            holder.append(fn())
        except BaseException as exc:  # noqa: BLE001 — исключение потока возвращается тесту
            errors.append(exc)

    thread = threading.Thread(target=body, name=name, daemon=True)
    run = _Run(thread, holder, errors)
    thread.start()
    return run


def _call_bounded(fn: Callable[[], Any], deadline_s: float, *, swallow: bool = False) -> Any:
    run = _start("t53h-bounded", fn)
    run.thread.join(deadline_s)
    if run.thread.is_alive():
        if swallow:
            return None
        pytest.fail(f"вызов не вернулся за {deadline_s} с")
    if run.error:
        if swallow:
            return None
        raise run.error[0]
    return run.result[0] if run.result else None


def _join_all(runs: list[_Run], deadline_s: float, what: str) -> None:
    for run in runs:
        run.thread.join(deadline_s)
    alive = [r.thread.name for r in runs if r.thread.is_alive()]
    assert alive == [], f"{what}: потоки не завершились за {deadline_s} с: {alive}"
    for run in runs:
        if run.error:
            raise run.error[0]


def _disconnect_in_window(
    rig: _Rig,
    gate: _Gate,
    starter: Callable[[], _Run],
    *,
    plugin_order: bool = False,
    deadline_s: float = _DEADLINE_S,
    disc_probe_s: float = _DISC_PROBE_S,
) -> _Run:
    """Запустить ``connect`` (или тик), дождаться паузы в потоке запуска, позвать ``disconnect`` и отпустить паузу.

    Возвращает прогон запуска (``result[0]`` — значение ``connect()``); к возврату оба потока завершены.
    """
    started = starter()
    if not gate.entered.wait(deadline_s):
        gate.release.set()
        started.thread.join(deadline_s)
        pytest.fail("окно недостижимо: пауза в точке не наступила из потока connect за дедлайн")
    assert gate.thread is started.thread, "пауза наступила не в потоке connect/tick"

    def disconnect() -> None:
        if plugin_order:
            rig.drv.desired_connected = False  # порядок плагина: сначала desired, затем disconnect
        rig.drv.disconnect()

    disc = _start("t53h-disconnect", disconnect)
    disc.thread.join(disc_probe_s)  # вправе ждать connect — не требуем возврата до отпускания паузы
    gate.release.set()
    _join_all([disc, started], deadline_s, "после отпускания паузы")
    return started


def _start_connect(rig: _Rig) -> Callable[[], _Run]:
    return lambda: _start("t53h-connect", rig.drv.connect)


# ==================================================================================================
# B4: обычный случай (первый тест файла — короткий дедлайн)
# ==================================================================================================


def test_b4_disconnect_after_connect_one_soft(make_rig: Callable[..., _Rig]) -> None:
    """``connect()`` вернул True, затем ``disconnect()``: ровно одна запись стопа уровня 1."""
    rig = make_rig()
    assert _call_bounded(rig.drv.connect, _FIRST_DEADLINE_S) is True
    assert rig.client.stops == []  # до отключения стопов нет
    _call_bounded(rig.drv.disconnect, _FIRST_DEADLINE_S)
    assert rig.client.stops == [_SOFT]


# ==================================================================================================
# B1: связь поднята, робот не готов, disconnect внутри connect -> 1 SOFT, connect False
# ==================================================================================================


def _assert_window_one_soft(rig: _Rig, started: _Run) -> None:
    assert rig.client.stops == [_SOFT]
    assert started.result == [False]
    assert rig.drv.is_connected is False


def test_b1_disconnect_inside_probe_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    gate = rig.gate("probe")
    started = _disconnect_in_window(rig, gate, _start_connect(rig))
    _assert_window_one_soft(rig, started)


def test_b1_disconnect_inside_sync_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    gate = rig.gate("sync")
    started = _disconnect_in_window(rig, gate, _start_connect(rig))
    _assert_window_one_soft(rig, started)


def test_b1_disconnect_inside_on_connect_read_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    gate = rig.gate("read")
    started = _disconnect_in_window(rig, gate, _start_connect(rig))
    _assert_window_one_soft(rig, started)


# ==================================================================================================
# B2: готовый робот, повторный connect, disconnect внутри probe -> 1 SOFT
# ==================================================================================================


def test_b2_ready_robot_disconnect_inside_probe_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    assert _call_bounded(rig.drv.connect, _DEADLINE_S) is True
    rig.client.stops.clear()  # считаем только записи за этот disconnect
    gate = rig.gate("probe")
    started = _disconnect_in_window(rig, gate, _start_connect(rig))
    assert rig.client.stops == [_SOFT]
    assert started.result == [False]


# ==================================================================================================
# B3: связь не поднята -> 0 записей (вместе с проверкой достижимости окна)
# ==================================================================================================


def test_b3_disconnect_inside_transport_connect_no_write(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(transport_connected=False)
    gate = rig.gate("connect")
    started = _disconnect_in_window(rig, gate, _start_connect(rig))
    assert gate.entered.is_set()  # окно было достигнуто: «0 записей» не вакуумно
    assert rig.client.stops == []
    assert started.result == [False]


def test_b3_disconnect_while_closing_stale_socket_no_write(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig(transport_connected=True)  # подключённый старый сокет: connect закрывает его первым делом
    gate = rig.gate("disconnect")
    started = _disconnect_in_window(rig, gate, _start_connect(rig))
    assert gate.entered.is_set()
    assert rig.client.stops == []
    assert started.result == [False]


# ==================================================================================================
# B4b: disconnect посреди повторного connect, затем connect() -> True: «останавливается» снято
# ==================================================================================================


def test_b4_disconnect_then_connect_clears_stopping(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()
    assert _call_bounded(rig.drv.connect, _DEADLINE_S) is True
    gate = rig.gate("probe")
    started = _disconnect_in_window(rig, gate, _start_connect(rig))
    assert started.result == [False]
    # пауза уже сработала один раз и больше не держит: следующий connect идёт без неё
    assert _call_bounded(rig.drv.connect, _DEADLINE_S) is True
    assert rig.drv.state.view().stopping is False
    answer = _call_bounded(lambda: rig.drv.call("jog_hold", dict(_JOG)), _DEADLINE_S)
    assert _STOPPING_TEXT not in str(answer.get("message", ""))


# ==================================================================================================
# B5: переподключение тика, plugin-порядок «Отключить» -> 1 SOFT, не «сдался», транспорт закрыт
# ==================================================================================================


def test_b5_tick_reconnect_disconnect_inside_probe_one_soft(make_rig: Callable[..., _Rig]) -> None:
    rig = make_rig()  # робот не готов: connect() ни разу не вызывали
    rig.drv.desired_connected = True
    rig.drv.max_reconnect_attempts = 1
    gate = rig.gate("probe")
    starter = lambda: _start("t53h-tick", lambda: rig.drv.tick())  # noqa: E731
    _disconnect_in_window(rig, gate, starter, plugin_order=True)
    assert rig.client.stops == [_SOFT]
    assert rig.drv.reconnect_exhausted is False
    assert rig.transport.is_connected is False
