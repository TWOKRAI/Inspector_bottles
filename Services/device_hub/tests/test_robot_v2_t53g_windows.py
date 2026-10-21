"""T5.3g шаг 1 — проба окон W1, W4 и WW ``RobotDriverV2`` барьером (тесты опасности, до правки).

Сценарий каждой пробы: простой робот (нет задания, программы и jog), поток T1 — ``driver.connect()``,
поток T2 (поток теста) — ``driver.request_stop(deadline=сейчас + малый срок)`` внутри окна.

Барьер — единственная подмена: обёртка, которая ставит паузу ТОЛЬКО в потоке T1 и ТОЛЬКО после возврата
исходного вызова: T1 ставит ``entered`` и ждёт ``release`` (с таймаутом). T2 ждёт ``entered`` (не дождался —
тест падает с сообщением о недостижимости окна), зовёт ``request_stop``, проверяет, что T1 всё ещё стоит в окне,
и ставит ``release``. T1 — daemon-поток, ``join`` с дедлайном.

- W1: пауза после ``RobotState.is_shutdown()`` вернул False в ``_connect_locked`` (перед ``self._ready = True``).
- W4: робот подключён до T1; пауза после ``RobotState.connect_check()`` вернул (False, False) в ``_connect_locked``
  (перед ``connect_reset``); эхо стопа не приходит (фейк ``await_stop_echo`` бросает).
- WW: пауза внутри ``client.probe()`` (фейковый клиент).

Ожидаемые значения — решение владельца 2026-10-20: простой робот, которому ``request_stop`` пришёл посреди
``connect``, считается подключённым и получает один SOFT; «готов» после выключения — никогда. Прогнозы на main —
``plans/robot-protocol-v2/tasks/T5.3g.probe.md``. Одна строка таблицы — один тест; сообщение несёт наблюдение.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2, RobotState
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID

_SOFT = 1  # STOP_LEVEL["SOFT"] протокола v2 (protocol-spec): литерал, не значение из кода драйвера
_TEXT_STOPPING = "драйвер робота останавливается"
_ENTER_S = 5.0  # T2 ждёт входа T1 в окно
_RELEASE_S = 10.0  # T1 ждёт «пусти» не дольше
_JOIN_S = 10.0  # дедлайн join потока T1
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
    def __init__(self) -> None:
        self.is_connected = True
        self.tlm = _free_tlm()

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def read_registers(self, _address: int, _count: int) -> list[int]:
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

    def probe(self) -> None:
        self.on_probe()

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


def _make_driver() -> tuple[RobotDriverV2, _FakeClient]:
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
    drv = RobotDriverV2(entry, None, transport=_FakeTransport(), publish=lambda _p, _v: None, spawn=_SCOPE.spawn)
    client = _FakeClient()
    drv._client = client  # шов: клиент v2 без sim (как test_robot_driver_v2._fake_driver)
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


def _run_window(drv: RobotDriverV2, client: _FakeClient, barrier: _Barrier, window: str) -> dict[str, Any]:
    """T1 — ``connect()`` до барьера; T2 — ``request_stop`` внутри окна; наблюдение после join T1."""
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
    drv.request_stop(deadline=time.monotonic() + _STOP_DEADLINE_S)
    # T2 отработал, пока T1 стоит в окне: иначе проба ничего не говорит
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
    _bounded(drv.disconnect, _JOIN_S, "disconnect")


def _caller_is_connect_locked() -> bool:
    # кадр 0 — этот, 1 — обёртка, 2 — вызывающий метод драйвера
    return sys._getframe(2).f_code.co_name == "_connect_locked"


# --------------------------------------------------------------------------------------------------
# W1: после is_shutdown() == False, до self._ready = True
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def w1(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    drv, client = _make_driver()
    barrier = _Barrier()
    original = RobotState.is_shutdown

    def is_shutdown(self: RobotState) -> bool:
        result = original(self)
        if result is False and _caller_is_connect_locked():
            barrier.pause_if_t1()
        return result

    monkeypatch.setattr(RobotState, "is_shutdown", is_shutdown)
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
# W4: робот подключён; после connect_check() == (False, False), до connect_reset()
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def w4(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    drv, client = _make_driver()
    assert _bounded(drv.connect, _JOIN_S, "W4 предварительный connect") is True, "W4: робот не подключился до T1"
    client.echo = False  # запись стопа T2 остаётся без эха
    barrier = _Barrier()
    original = RobotState.connect_check

    def connect_check(self: RobotState) -> tuple[bool, bool]:
        result = original(self)
        if result == (False, False) and _caller_is_connect_locked():
            barrier.pause_if_t1()
        return result

    monkeypatch.setattr(RobotState, "connect_check", connect_check)
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
