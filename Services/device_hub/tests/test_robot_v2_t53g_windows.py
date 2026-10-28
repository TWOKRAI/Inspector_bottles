"""T5.3g шаг 1 — проба окон W1, W4 и WW ``RobotDriverV2`` барьером (тесты опасности, до правки).

Сценарий каждой пробы: простой робот (нет задания, программы и jog), поток T1 — ``driver.connect()``,
поток T2 (поток теста) — ``driver.request_stop(deadline=сейчас + малый срок)`` внутри окна.

Барьер — единственная подмена: обёртка, которая ставит паузу ТОЛЬКО в потоке T1 и ТОЛЬКО после возврата
исходного вызова: T1 ставит ``entered`` и ждёт ``release`` (с таймаутом). T2 ждёт ``entered`` (не дождался —
тест падает с сообщением о недостижимости окна), зовёт ``request_stop``, проверяет, что T1 всё ещё стоит в окне,
и ставит ``release``. T1 — daemon-поток, ``join`` с дедлайном.

- W1: пауза в ``_connect_locked`` ДО вызова ``RobotState.connect_finish()`` (после правки T5.3g окно — вход в переход).
- W4: робот подключён до T1; пауза после того, как ``RobotState.connect_begin()`` вернул ``("go", True)`` в
  ``_connect_locked``; эхо стопа не приходит (фейк ``await_stop_echo`` бросает).
- WW: пауза внутри ``client.probe()`` (фейковый клиент).
- Тесты автора T5.3g: W1' (T1 выходит из ``connect`` между секциями ``request_stop``), WW-c (готовый робот),
  A3 (запись до связи), A4 (стоп после ``connect_finish``), Q4 (нет SERVO после стопа), disconnect посреди
  ``on_connect``.

Ожидаемые значения — решение владельца 2026-10-20: простой робот, которому ``request_stop`` пришёл посреди
``connect``, считается подключённым и получает один SOFT; «готов» после выключения — никогда. Прогнозы на main —
``plans/robot-protocol-v2/tasks/T5.3g.probe.md``. Одна строка таблицы — один тест; сообщение несёт наблюдение.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2, RobotState
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import Move, Point, Program

_SOFT = 1  # STOP_LEVEL["SOFT"] протокола v2 (protocol-spec): литерал, не значение из кода драйвера
_TEXT_STOPPING = "драйвер робота останавливается"
_ENTER_S = 5.0  # T2 ждёт входа T1 в окно
_RELEASE_S = 10.0  # T1 ждёт «пусти» не дольше
_JOIN_S = 10.0  # дедлайн join потока T1
_HANG_S = 5.0  # дедлайн request_stop и disconnect: зависание даёт красный за секунды
_STOP_DEADLINE_S = 0.5  # срок request_stop: малый (эхо ждёт до срока)
_SCOPE_BUDGET_S = 6.0
_JOG = {"dir": 1, "spd": 20}

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2t53g", budget_s=_SCOPE_BUDGET_S)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


# --------------------------------------------------------------------------------------------------
# Фейки на границе драйвера (копия схемы test_robot_driver_v2.py: транспорт внедряется, клиент — шов)
# --------------------------------------------------------------------------------------------------


def _free_tlm() -> list[int]:
    """Блок TLM: серво включено, метка параметров 1, остальное 0."""
    base = REG["TLM_PROTO_VER"]
    words = [0] * 32
    words[REG["TLM_SERVO"] - base] = 1
    words[REG["TLM_CFG_EPOCH"] - base] = 1
    return words


class _FakeTransport:
    """Фейковый транспорт; крючки ``on_connect`` / ``on_disconnect`` / ``on_read`` — для барьера в потоке T1."""

    def __init__(self, *, connected: bool = True, servo_tlm: int = 1) -> None:
        self.is_connected = connected
        self.tlm = _free_tlm()
        self.tlm[REG["TLM_SERVO"] - REG["TLM_PROTO_VER"]] = servo_tlm
        self.on_connect: Callable[[], None] = lambda: None  # после is_connected = True (как device.py:103)
        self.on_disconnect: Callable[[], None] = lambda: None  # до сброса is_connected
        self.on_read: Callable[[], None] = lambda: None

    def connect(self) -> bool:
        self.is_connected = True
        self.on_connect()
        return True

    def disconnect(self) -> None:
        self.on_disconnect()
        self.is_connected = False

    def read_registers(self, _address: int, _count: int) -> list[int]:
        self.on_read()
        return list(self.tlm)


class _FakeClient:
    """Клиент v2: пишет уровни ``issue_stop``; эхо стопа — по флагу ``echo``; ``probe`` — с крючком барьера."""

    heartbeat_period_s = None
    jog_lease_period_s = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.stops: list[int] = []
        self.echo = True
        self.on_probe: Callable[[], None] = lambda: None
        self.probes = 0
        self.servo_calls: list[bool] = []
        self.transport: _FakeTransport | None = None
        self.jog_conts: list[tuple[int, int]] = []
        self.run_started = threading.Event()
        self.run_release = threading.Event()

    def probe(self) -> None:
        self.probes += 1
        self.on_probe()

    def jog_cont(self, direction: int, speed: int) -> Any:
        """JOG_CONT: пишет вызов в список, ``seq`` - его номер."""
        self.jog_conts.append((direction, speed))
        return SimpleNamespace(seq=len(self.jog_conts))

    def jog_lease(self) -> None:
        pass

    def run_chunks(self, _scenario: Any, *, params: Any, on_progress: Any) -> None:
        """Программа держит исполнитель, пока тест не поставит ``run_release``."""
        self.run_started.set()
        self.run_release.wait(_RELEASE_S)

    def servo(self, on: bool) -> None:
        """SERVO: считает вызовы и ставит бит TLM_SERVO в фейковом транспорте."""
        self.servo_calls.append(on)
        if self.transport is not None:
            self.transport.tlm[REG["TLM_SERVO"] - REG["TLM_PROTO_VER"]] = 1 if on else 0

    def sync_params(self, _values: Any, _epoch: int, *, cancelled: Any = None) -> None:
        pass

    def kick_heartbeat(self) -> None:
        pass

    def poll_errors(self) -> list:
        return []

    def stop(self, level: int) -> None:
        with self._lock:
            self.stops.append(level)

    def issue_stop(self, level: int) -> int:
        self.stop(level)
        with self._lock:
            return len(self.stops) * 4 + level

    def await_stop_echo(self, _value: int, _level: int, *, deadline: float) -> None:
        if not self.echo:
            raise TimeoutError("эхо стопа не пришло (фейк)")

    def soft_count(self) -> int:
        with self._lock:
            return sum(1 for level in self.stops if level == _SOFT)

    def levels(self) -> list[int]:
        with self._lock:
            return list(self.stops)


def _make_driver(
    *, connected: bool = True, servo_tlm: int = 1, clock: Callable[[], float] | None = None
) -> tuple[RobotDriverV2, _FakeClient]:
    entry = DeviceEntry(
        id="rv2",
        name="rv2",
        kind="robot",
        protocol="delta_v2",
        # timeout_sec/retries малые: бюджет записи 0,05 с — у request_stop с малым сроком есть окно чтения эха
        transport={
            "type": "tcp",
            "host": "127.0.0.1",
            "port": 1,
            "unit_id": ROBOT_UNIT_ID,
            "timeout_sec": 0.05,
            "retries": 0,
        },
        params={},
    )
    transport = _FakeTransport(connected=connected, servo_tlm=servo_tlm)
    client = _FakeClient()
    client.transport = transport
    drv = RobotDriverV2(
        entry,
        None,
        transport=transport,
        publish=lambda _p, _v: None,
        spawn=_SCOPE.spawn,
        clock=clock,
        client_factory=lambda _t, _c: client,  # шов: клиент v2 без sim (как test_robot_driver_v2._fake_driver)
    )
    return drv, client


def _bounded(fn: Callable[[], Any], deadline_s: float, what: str) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение переносится в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, name=f"t53g-{what}", daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"{what}: не вернулся за {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --------------------------------------------------------------------------------------------------
# Барьер и сценарий
# --------------------------------------------------------------------------------------------------


class _Barrier:
    """Пауза только в потоке T1, один раз, после возврата исходного вызова."""

    def __init__(self) -> None:
        self.t1: threading.Thread | None = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fired = False
        self.release_timed_out = False

    def pause_if_t1(self) -> bool:
        if threading.current_thread() is not self.t1 or self.fired:
            return False
        self.fired = True
        self.entered.set()
        if not self.release.wait(_RELEASE_S):
            self.release_timed_out = True
        return True


def _run_window(
    drv: RobotDriverV2,
    client: _FakeClient,
    barrier: _Barrier,
    window: str,
    *,
    stop: Callable[[], None] | None = None,
    released_by_stop: bool = False,
) -> dict[str, Any]:
    """T1 — ``connect()`` до барьера; T2 — ``stop`` (умолчание ``request_stop``) внутри окна; наблюдение после join T1.

    ``released_by_stop`` — барьер отпускает сам ``stop`` (W1'): T1 уже вышел, проверка «T1 стоит в окне» не нужна.
    """
    box: dict[str, Any] = {}

    def t1_body() -> None:
        try:
            box["connect"] = drv.connect()
        except BaseException as exc:  # noqa: BLE001 — наблюдение, не глушение: попадёт в отчёт
            box["connect_error"] = repr(exc)

    t1 = threading.Thread(target=t1_body, name=f"t53g-{window}-T1-connect", daemon=True)
    barrier.t1 = t1
    soft_before = client.soft_count()
    t1.start()
    reached = barrier.entered.wait(_ENTER_S)
    if not reached:
        barrier.release.set()
        t1.join(_JOIN_S)
        pytest.fail(f"{window}: окно недостижимо — барьер в T1 не сработал за {_ENTER_S} с; T1: {box}")
    # T2 под дедлайном: зависший драйвер (например, геттер берёт Lock) даёт красный тест, а не зависание
    if stop is None:
        _bounded(lambda: drv.request_stop(deadline=time.monotonic() + _STOP_DEADLINE_S), _HANG_S, "request_stop")
    else:
        _bounded(stop, _HANG_S, "stop")
    # T2 отработал, пока T1 стоит в окне: иначе проба ничего не говорит
    if released_by_stop:
        inside = barrier.release.is_set() and not barrier.release_timed_out
    else:
        inside = t1.is_alive() and not barrier.release.is_set() and not barrier.release_timed_out
    soft_during_stop = client.soft_count() - soft_before
    stop_unconfirmed_after_stop = drv.stop_unconfirmed
    barrier.release.set()
    t1.join(_JOIN_S)
    assert not t1.is_alive(), f"{window}: connect() не вернулся за {_JOIN_S} с после release"
    assert inside, f"{window}: request_stop прошёл не внутри окна (release_timed_out={barrier.release_timed_out})"
    view = drv.state.view()
    return {
        "connect": box.get("connect", box.get("connect_error")),
        "is_connected": drv.is_connected,
        "soft_during_stop": soft_during_stop,
        "levels": client.levels(),
        "probes": client.probes,
        "servo_calls": list(client.servo_calls),
        "is_shutdown": drv.state.is_shutdown(),
        "stopping": view.stopping,
        "stop_unconfirmed_after_stop": stop_unconfirmed_after_stop,
        "stop_unconfirmed": drv.stop_unconfirmed,
        "stop_unconfirmed_text": drv.stop_unconfirmed_text,
    }


class _Observed(dict):
    """Наблюдение сценария; сбой самой пробы (окно недостижимо, зависание) поднимается в тесте, не в фикстуре."""

    def __getitem__(self, key: str) -> Any:
        error = dict.get(self, "probe_error")
        if error is not None:
            raise error
        return dict.__getitem__(self, key)

    def __repr__(self) -> str:
        return repr({k: v for k, v in self.items() if k != "probe_error"})


def _capture(scenario: Callable[[], dict[str, Any]]) -> _Observed:
    # сбой пробы — провал теста строки (FAILED), а не ошибка фикстуры (ERROR)
    try:
        return _Observed(scenario())
    except BaseException as exc:  # noqa: BLE001 — pytest.fail бросает BaseException; поднимется в тесте
        return _Observed(probe_error=exc)


def _teardown(drv: RobotDriverV2) -> None:
    _bounded(drv.disconnect, _HANG_S, "disconnect")


def _observe(
    drv: RobotDriverV2,
    client: _FakeClient,
    barrier: _Barrier,
    window: str,
    *,
    stop: Callable[[], None] | None = None,
    released_by_stop: bool = False,
) -> dict[str, Any]:
    """Сценарий окна с уборкой для тестов автора без фикстуры: сбой пробы — FAILED теста."""
    try:
        return _run_window(drv, client, barrier, window, stop=stop, released_by_stop=released_by_stop)
    finally:
        barrier.release.set()
        _teardown(drv)


def _caller_is_connect_locked() -> bool:
    # кадр 0 — этот, 1 — обёртка, 2 — вызывающий метод драйвера
    return sys._getframe(2).f_code.co_name == "_connect_locked"


# --------------------------------------------------------------------------------------------------
# Сторож быстроты: первый тест файла (ловушка "геттер ready берёт Lock" краснеет за секунды, а не за минуты)
# --------------------------------------------------------------------------------------------------


def test_request_stop_returns_quickly_on_connected_robot() -> None:
    """Простой подключённый робот: ``request_stop`` возвращается за 1 с и пишет ровно один SOFT.

    Зависание (например, геттер ``RobotState.ready`` под тем же ``Lock``, что держит ``process_stop_plan``) даёт
    «не вернулся за 1.0 с» в первом же тесте; разборка теста тоже под коротким дедлайном.
    """
    drv, client = _make_driver()
    cleanup_failure: AssertionError | None = None
    try:
        assert _bounded(drv.connect, _HANG_S, "connect") is True, "робот не подключился (настройка теста)"
        _bounded(lambda: drv.request_stop(deadline=time.monotonic() + _STOP_DEADLINE_S), 1.0, "request_stop")
        assert client.soft_count() == 1, f"записей SOFT за request_stop {client.soft_count()}, хотим 1"
    finally:
        try:
            _bounded(drv.disconnect, 1.0, "disconnect")
        except AssertionError as exc:  # не затирает падение тела теста; без него - сам отказ
            cleanup_failure = exc
    assert cleanup_failure is None, f"разборка теста: {cleanup_failure}"


# --------------------------------------------------------------------------------------------------
# W1: вход в connect_finish (до перехода)
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def w1(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    drv, client = _make_driver()
    barrier = _Barrier()
    original = RobotState.connect_finish

    def connect_finish(self: RobotState) -> bool:
        if _caller_is_connect_locked():
            barrier.pause_if_t1()
        return original(self)

    monkeypatch.setattr(RobotState, "connect_finish", connect_finish)
    try:
        yield _capture(lambda: _run_window(drv, client, barrier, "W1"))
    finally:
        barrier.release.set()
        _teardown(drv)


def test_w1_a_connect_returns_false(w1: dict[str, Any]) -> None:
    assert w1["connect"] is False, f"W1-a: connect() вернул {w1['connect']!r}, хотим False; наблюдение: {w1}"


def test_w1_b_not_connected_after(w1: dict[str, Any]) -> None:
    assert w1["is_connected"] is False, f"W1-b: is_connected={w1['is_connected']!r}, хотим False; наблюдение: {w1}"


def test_w1_c_one_soft_during_request_stop(w1: dict[str, Any]) -> None:
    assert w1["soft_during_stop"] == 1, (
        f"W1-c: записей STOP_REQ SOFT за request_stop {w1['soft_during_stop']}, хотим 1; наблюдение: {w1}"
    )


def test_w1_d_shutdown_latched(w1: dict[str, Any]) -> None:
    assert w1["is_shutdown"] is True, f"W1-d: is_shutdown()={w1['is_shutdown']!r}, хотим True; наблюдение: {w1}"


# --------------------------------------------------------------------------------------------------
# W4: робот подключён; после того, как connect_begin() вернул ("go", True)
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def w4(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    drv, client = _make_driver()
    assert _bounded(drv.connect, _JOIN_S, "W4 предварительный connect") is True, "W4: робот не подключился до T1"
    client.echo = False  # запись стопа T2 остаётся без эха
    barrier = _Barrier()
    original = RobotState.connect_begin

    def connect_begin(self: RobotState) -> tuple[str, bool]:
        result = original(self)
        if result == ("go", True) and _caller_is_connect_locked():
            barrier.pause_if_t1()
        return result

    monkeypatch.setattr(RobotState, "connect_begin", connect_begin)
    try:

        def scenario() -> dict[str, Any]:
            obs = _run_window(drv, client, barrier, "W4")
            obs["jog_hold"] = _bounded(lambda: drv.call("jog_hold", dict(_JOG)), _JOIN_S, "jog_hold")
            return obs

        yield _capture(scenario)
    finally:
        barrier.release.set()
        _teardown(drv)


def test_w4_a_connect_returns_false(w4: dict[str, Any]) -> None:
    assert w4["connect"] is False, f"W4-a: connect() вернул {w4['connect']!r}, хотим False; наблюдение: {w4}"


def test_w4_b_stopping_after(w4: dict[str, Any]) -> None:
    assert w4["stopping"] is True, f"W4-b: stopping={w4['stopping']!r}, хотим True; наблюдение: {w4}"


def test_w4_c_jog_hold_says_stopping(w4: dict[str, Any]) -> None:
    reply = w4["jog_hold"]
    assert reply.get("message") == _TEXT_STOPPING, (
        f"W4-c: jog_hold ответил {reply!r}, хотим {_TEXT_STOPPING!r}; наблюдение: {w4}"
    )


def test_w4_d_stop_unconfirmed_survives(w4: dict[str, Any]) -> None:
    assert w4["stop_unconfirmed"] is True, (
        f"W4-d: stop_unconfirmed={w4['stop_unconfirmed']!r} после connect, хотим True; наблюдение: {w4}"
    )


def test_w4_e_one_soft_during_request_stop(w4: dict[str, Any]) -> None:
    assert w4["soft_during_stop"] == 1, (
        f"W4-e: записей STOP_REQ SOFT за request_stop {w4['soft_during_stop']}, хотим 1; наблюдение: {w4}"
    )


# --------------------------------------------------------------------------------------------------
# WW: внутри client.probe()
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def ww() -> Iterator[dict[str, Any]]:
    drv, client = _make_driver()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    try:
        yield _capture(lambda: _run_window(drv, client, barrier, "WW"))
    finally:
        barrier.release.set()
        _teardown(drv)


def test_ww_a_one_soft_during_request_stop(ww: dict[str, Any]) -> None:
    assert ww["soft_during_stop"] == 1, (
        f"WW-a: записей STOP_REQ SOFT за request_stop {ww['soft_during_stop']}, хотим 1; наблюдение: {ww}"
    )


def test_ww_b_connect_returns_false(ww: dict[str, Any]) -> None:
    assert ww["connect"] is False, f"WW-b: connect() вернул {ww['connect']!r}, хотим False; наблюдение: {ww}"


# --------------------------------------------------------------------------------------------------
# Тесты автора T5.3g: W1', WW-c, A3, A4, Q4, disconnect посреди on_connect
# --------------------------------------------------------------------------------------------------


def test_w1p_soft_when_connect_exits_between_stop_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    """W1': T1 стоит в probe; T2 между ``request_stop_begin`` и ``process_stop_plan`` ждёт выхода T1 из connect."""
    drv, client = _make_driver()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    original = RobotState.process_stop_plan

    def process_stop_plan(self: RobotState, *args: Any, **kwargs: Any) -> Any:
        if threading.current_thread() is not barrier.t1 and barrier.entered.is_set() and not barrier.release.is_set():
            barrier.release.set()
            assert barrier.t1 is not None
            barrier.t1.join(_JOIN_S)  # T1 выходит из connect (отказ, connect_end) между секциями request_stop
            assert not barrier.t1.is_alive(), "W1p: T1 не вышел из connect за дедлайн (находка, не таймаут теста)"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(RobotState, "process_stop_plan", process_stop_plan)
    obs = _observe(drv, client, barrier, "W1p", released_by_stop=True)
    assert obs["soft_during_stop"] == 1, f"W1p: записей SOFT за request_stop {obs['soft_during_stop']}, хотим 1; {obs}"
    assert obs["connect"] is False, f"W1p: connect() вернул {obs['connect']!r}, хотим False; {obs}"


def test_ww_c_ready_robot_connect_false() -> None:
    """WW-c: робот подключён до T1, стоп внутри probe -> ``connect()`` False, ``is_connected`` False."""
    drv, client = _make_driver()
    assert _bounded(drv.connect, _JOIN_S, "WW-c предварительный connect") is True, "WW-c: робот не подключился до T1"
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "WWc")
    assert obs["connect"] is False, f"WW-c: connect() вернул {obs['connect']!r}, хотим False; {obs}"
    assert obs["is_connected"] is False, f"WW-c: is_connected={obs['is_connected']!r}, хотим False; {obs}"


def test_a3_no_write_inside_transport_connect() -> None:
    """A3: стоп внутри ``transport.connect()`` (флаг уже True, как device.py:103) -> записи нет, probe не зовётся."""
    drv, client = _make_driver(connected=False)
    barrier = _Barrier()
    client.transport.on_connect = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "A3-connect")
    assert obs["levels"] == [], f"A3: записи STOP_REQ {obs['levels']}, хотим []; {obs}"
    assert obs["stop_unconfirmed"] is False, f"A3: stop_unconfirmed={obs['stop_unconfirmed']!r}, хотим False; {obs}"
    assert obs["connect"] is False, f"A3: connect() вернул {obs['connect']!r}, хотим False; {obs}"
    assert obs["probes"] == 0, f"A3: фейковый probe вызван {obs['probes']} раз, хотим 0 (инъекция 12); {obs}"


def test_a3_no_write_while_closing_stale_socket() -> None:
    """A3: робот не готов, транспорт «подключён»; стоп, пока connect закрывает старый сокет -> записи нет."""
    drv, client = _make_driver(connected=True)
    barrier = _Barrier()
    client.transport.on_disconnect = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "A3-stale")
    assert obs["levels"] == [], f"A3: записи STOP_REQ {obs['levels']}, хотим []; {obs}"
    assert obs["connect"] is False, f"A3: connect() вернул {obs['connect']!r}, хотим False; {obs}"


def test_a4_stop_after_connect_finish_one_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4 (страж регресса): стоп после ``connect_finish`` -> ``connect()`` True, ровно 1 SOFT."""
    drv, client = _make_driver()
    barrier = _Barrier()
    original = RobotState.connect_finish

    def connect_finish(self: RobotState) -> bool:
        result = original(self)
        if result is True and _caller_is_connect_locked():
            barrier.pause_if_t1()
        return result

    monkeypatch.setattr(RobotState, "connect_finish", connect_finish)
    obs = _observe(drv, client, barrier, "A4")
    assert obs["connect"] is True, f"A4: connect() вернул {obs['connect']!r}, хотим True; {obs}"
    assert obs["soft_during_stop"] == 1, f"A4: записей SOFT {obs['soft_during_stop']}, хотим 1; {obs}"


def test_q4_no_servo_after_stop_in_on_connect() -> None:
    """Q4: стоп посреди ``_run_on_connect`` (пауза в чтении TLM) -> SERVO не шлётся, ``connect()`` False."""
    drv, client = _make_driver(servo_tlm=0)
    barrier = _Barrier()
    client.transport.on_read = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "Q4")
    assert obs["servo_calls"] == [], f"Q4: вызовы servo {obs['servo_calls']}, хотим []; {obs}"
    assert obs["connect"] is False, f"Q4: connect() вернул {obs['connect']!r}, хотим False; {obs}"


def test_disconnect_during_on_connect_connect_false() -> None:
    """Уточнение 1: обычный ``disconnect`` посреди ``_run_on_connect`` -> ``connect()`` и ``is_connected`` False."""
    # TLM_SERVO уже 1: SERVO не нужен, отмены перед записью нет, до connect_finish доходит только его проверка _stopping
    drv, client = _make_driver()
    barrier = _Barrier()
    client.transport.on_read = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "disconnect", stop=drv.disconnect)
    assert obs["connect"] is False, f"disconnect: connect() вернул {obs['connect']!r}, хотим False; {obs}"
    assert obs["is_connected"] is False, f"disconnect: is_connected={obs['is_connected']!r}, хотим False; {obs}"


def test_failed_connect_then_request_stop_no_soft() -> None:
    """Инъекция 13: ``probe`` бросает не транспортную ошибку после ``connect_link_up`` -> ``connect()`` False;
    затем ``request_stop`` не пишет (``connect_end`` снял пометки на выходе): неподключённый простой робот без SOFT."""
    drv, client = _make_driver(connected=False)

    def failing_probe() -> None:
        raise RuntimeError("protocol mismatch (fake)")  # не транспортная ошибка: сокет остаётся открытым

    client.on_probe = failing_probe
    try:
        result = _bounded(drv.connect, _JOIN_S, "connect")
        assert result is False, f"connect() вернул {result!r}, хотим False (настройка теста)"
        assert client.transport is not None and client.transport.is_connected, "сокет должен остаться открытым"
        _bounded(lambda: drv.request_stop(deadline=time.monotonic() + _STOP_DEADLINE_S), _HANG_S, "request_stop")
        observed = {"levels": client.levels(), "stop_unconfirmed": drv.stop_unconfirmed}
    finally:
        _teardown(drv)
    assert observed == {"levels": [], "stop_unconfirmed": False}, f"после неудачного connect: {observed}"


def _frozen_clock() -> float:
    """Часы стоят: окно удержания jog (0,2 с) не истекает, поводок не пишет свой стоп посреди теста."""
    return 1000.0


def test_a5_connect_during_jog_no_new_writes() -> None:
    """A5: активный jog посреди ``connect`` -> ``connect()`` True, probe и записей нет, ``is_connected`` True."""
    drv, client = _make_driver(clock=_frozen_clock)
    try:
        assert _bounded(drv.connect, _JOIN_S, "connect") is True, "робот не подключился (настройка теста)"
        reply = _bounded(lambda: drv.call("jog_hold", dict(_JOG)), _JOIN_S, "jog_hold")
        assert reply.get("status") == "ok", f"jog не запущен (настройка теста): {reply!r}"
        probes = client.probes
        result = _bounded(drv.connect, _JOIN_S, "connect во время jog")
        observed = {
            "connect": result,
            "probes_added": client.probes - probes,
            "levels": client.levels(),
            "is_connected": drv.is_connected,
        }
    finally:
        _teardown(drv)
    assert observed == {"connect": True, "probes_added": 0, "levels": [], "is_connected": True}, f"A5 jog: {observed}"


def test_a5_connect_during_program_no_new_writes() -> None:
    """A5: активная программа посреди ``connect`` -> ``connect()`` True, probe и записей нет, ``is_connected`` True."""
    drv, client = _make_driver()
    program = Program(name="t53g", steps=(Move(point="a", kind="JOINT"),))
    points = {"a": Point(name="a", x=400, y=100, z=-60, rz=0, hand=1)}
    try:
        assert _bounded(drv.connect, _JOIN_S, "connect") is True, "робот не подключился (настройка теста)"
        started = _bounded(lambda: drv.start_program(program, points, None, name="t53g"), _JOIN_S, "start_program")
        assert started.get("status") == "ok", f"программа не запущена (настройка теста): {started!r}"
        assert client.run_started.wait(_ENTER_S), "достижимость: исполнитель не дошёл до run_chunks"
        probes = client.probes
        result = _bounded(drv.connect, _JOIN_S, "connect во время программы")
        observed = {
            "connect": result,
            "probes_added": client.probes - probes,
            "levels": client.levels(),
            "is_connected": drv.is_connected,
        }
    finally:
        client.run_release.set()
        _teardown(drv)
    assert observed == {"connect": True, "probes_added": 0, "levels": [], "is_connected": True}, f"A5 prog: {observed}"
