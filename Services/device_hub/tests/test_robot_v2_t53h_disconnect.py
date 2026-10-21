"""T5.3h шаг 1 — проба: обычный ``disconnect()`` посреди ``connect`` ``RobotDriverV2`` (тесты опасности, до правки).

Решение владельца 2026-10-21: простой робот, которому обычное «Отключить» пришло после подъёма связи (граница A3 —
``connect_link_up``), считается подключённым и получает ровно один SOFT; до A3 — записи нет (правило 2026-10-19).

Обвязка — ``test_robot_v2_t53g_windows.py`` (импортом, без копии): T1 — ``connect()`` (или ``tick()``) с паузой
только в T1; T2 — ``drv.disconnect()`` под дедлайном. Каждое «0 записей» идёт вместе с проверкой достижимости окна.
Прогнозы на main и таблица — ``plans/robot-protocol-v2/tasks/T5.3h.probe.md``; одна строка таблицы — один тест.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2, RobotState
from Services.device_hub.tests.test_robot_v2_t53g_windows import (
    _ENTER_S,
    _HANG_S,
    _JOIN_S,
    _Barrier,
    _bounded,
    _caller_is_connect_locked,
    _capture,
    _FakeClient,
    _make_driver,
    _observe,
    _run_window,
    _teardown,
    driver_scope,  # noqa: F401 — autouse-фикстура области потоков, нужна _make_driver
)

# --------------------------------------------------------------------------------------------------
# H0 — сторож быстроты: первый тест файла, дедлайн 1 с
# --------------------------------------------------------------------------------------------------


def test_h0_disconnect_returns_quickly_on_connected_robot() -> None:
    """H0: простой подключённый робот — ``disconnect`` возвращается за 1 с и пишет ровно один SOFT."""
    drv, client = _make_driver()
    assert _bounded(drv.connect, _HANG_S, "connect") is True, "робот не подключился (настройка теста)"
    _bounded(drv.disconnect, 1.0, "disconnect")
    assert client.soft_count() == 1, f"H0: записей SOFT за disconnect {client.soft_count()}, хотим 1"


# --------------------------------------------------------------------------------------------------
# H1: внутри client.probe() (после A3), робот не готов
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def h1() -> Iterator[dict[str, Any]]:
    drv, client = _make_driver()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    try:
        yield _capture(lambda: _run_window(drv, client, barrier, "H1", stop=drv.disconnect))
    finally:
        barrier.release.set()
        _teardown(drv)


def test_h1_a_one_soft_during_disconnect(h1: dict[str, Any]) -> None:
    assert h1["soft_during_stop"] == 1, f"H1-a: записей SOFT за disconnect {h1['soft_during_stop']}, хотим 1; {h1}"


def test_h1_b_connect_returns_false(h1: dict[str, Any]) -> None:
    assert h1["connect"] is False, f"H1-b: connect() вернул {h1['connect']!r}, хотим False; {h1}"


def test_h1_c_not_connected_after(h1: dict[str, Any]) -> None:
    assert h1["is_connected"] is False, f"H1-c: is_connected={h1['is_connected']!r}, хотим False; {h1}"


# --------------------------------------------------------------------------------------------------
# H2 — чтение TLM в _run_on_connect; H3 — вход в connect_finish; H4 — готовый робот внутри probe
# --------------------------------------------------------------------------------------------------


def test_h2_on_connect_read_one_soft() -> None:
    drv, client = _make_driver()
    barrier = _Barrier()
    client.transport.on_read = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "H2", stop=drv.disconnect)
    assert obs["soft_during_stop"] == 1, f"H2: записей SOFT за disconnect {obs['soft_during_stop']}, хотим 1; {obs}"


@pytest.fixture
def h3(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    drv, client = _make_driver()
    barrier = _Barrier()
    original = RobotState.connect_finish

    def connect_finish(self: RobotState) -> bool:
        if _caller_is_connect_locked():
            barrier.pause_if_t1()
        return original(self)

    monkeypatch.setattr(RobotState, "connect_finish", connect_finish)
    try:
        yield _capture(lambda: _run_window(drv, client, barrier, "H3", stop=drv.disconnect))
    finally:
        barrier.release.set()
        _teardown(drv)


def test_h3_a_one_soft_before_connect_finish(h3: dict[str, Any]) -> None:
    assert h3["soft_during_stop"] == 1, f"H3-a: записей SOFT за disconnect {h3['soft_during_stop']}, хотим 1; {h3}"


def test_h3_b_connect_returns_false(h3: dict[str, Any]) -> None:
    assert h3["connect"] is False, f"H3-b: connect() вернул {h3['connect']!r}, хотим False; {h3}"


def test_h4_ready_robot_inside_probe_one_soft() -> None:
    drv, client = _make_driver()
    assert _bounded(drv.connect, _JOIN_S, "H4 предварительный connect") is True, "H4: робот не подключился до T1"
    soft_before_t1 = client.soft_count()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "H4", stop=drv.disconnect)
    observed = {"soft_before_t1": soft_before_t1, "soft": obs["soft_during_stop"], "connect": obs["connect"]}
    assert observed == {"soft_before_t1": 0, "soft": 1, "connect": False}, f"H4: {observed}; {obs}"


# --------------------------------------------------------------------------------------------------
# H5 — аналог W1′: T1 выходит из connect между D2 (disconnect_stop_plan) и D3 (решение о SOFT)
# --------------------------------------------------------------------------------------------------


def test_h5_soft_when_connect_exits_between_disconnect_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    drv, client = _make_driver()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    original = RobotState.disconnect_stop_plan

    def disconnect_stop_plan(self: RobotState, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)  # _stopping уже стоит: connect выйдет с отказом
        if threading.current_thread() is not barrier.t1 and barrier.entered.is_set() and not barrier.release.is_set():
            barrier.release.set()
            assert barrier.t1 is not None
            barrier.t1.join(_JOIN_S)  # T1 выходит из connect (отказ, connect_end) между секциями disconnect
            assert not barrier.t1.is_alive(), "H5: T1 не вышел из connect за дедлайн (находка, не таймаут теста)"
        return result

    monkeypatch.setattr(RobotState, "disconnect_stop_plan", disconnect_stop_plan)
    obs = _observe(drv, client, barrier, "H5", stop=drv.disconnect, released_by_stop=True)
    observed = {"soft": obs["soft_during_stop"], "connect": obs["connect"]}
    assert observed == {"soft": 1, "connect": False}, f"H5: {observed}; {obs}"


# --------------------------------------------------------------------------------------------------
# H6, H7 — до A3: записи нет (правило 2026-10-19), должно остаться
# --------------------------------------------------------------------------------------------------


def test_h6_no_write_inside_transport_connect() -> None:
    drv, client = _make_driver(connected=False)
    barrier = _Barrier()
    client.transport.on_connect = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "H6", stop=drv.disconnect)
    observed = {"levels": obs["levels"], "connect": obs["connect"], "probes": obs["probes"]}
    assert observed == {"levels": [], "connect": False, "probes": 0}, f"H6: {observed}; {obs}"


def test_h7_no_write_while_closing_stale_socket() -> None:
    drv, client = _make_driver(connected=True)
    barrier = _Barrier()
    client.transport.on_disconnect = barrier.pause_if_t1
    obs = _observe(drv, client, barrier, "H7", stop=drv.disconnect)
    observed = {"levels": obs["levels"], "connect": obs["connect"]}
    assert observed == {"levels": [], "connect": False}, f"H7: {observed}; {obs}"


# --------------------------------------------------------------------------------------------------
# H8 — после connect_finish (страж регресса A4)
# --------------------------------------------------------------------------------------------------


def test_h8_after_connect_finish_one_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    drv, client = _make_driver()
    barrier = _Barrier()
    original = RobotState.connect_finish

    def connect_finish(self: RobotState) -> bool:
        result = original(self)
        if result is True and _caller_is_connect_locked():
            barrier.pause_if_t1()
        return result

    monkeypatch.setattr(RobotState, "connect_finish", connect_finish)
    obs = _observe(drv, client, barrier, "H8", stop=drv.disconnect)
    observed = {"soft": obs["soft_during_stop"], "connect": obs["connect"]}
    assert observed == {"soft": 1, "connect": True}, f"H8: {observed}; {obs}"


# --------------------------------------------------------------------------------------------------
# H9 (I1) — T2 стоит после D2, T1 — connect() целиком; затем T2 доделывает disconnect
# --------------------------------------------------------------------------------------------------


def test_h9_connect_inside_disconnect_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Страж дизайна: ``connect`` начат после ``disconnect_stop_plan`` и прошёл целиком до D3 — SOFT по живому
    ``is_connected``; хвост ``disconnect`` (D5, D6) снимает готовность и закрывает транспорт."""
    drv, client = _make_driver()
    t2_entered = threading.Event()
    t2_release = threading.Event()
    box: dict[str, Any] = {}
    original = RobotState.disconnect_stop_plan

    def disconnect_stop_plan(self: RobotState, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        if threading.current_thread().name == "t53h-H9-T2":
            t2_entered.set()
            box["t2_release_ok"] = t2_release.wait(_JOIN_S)
        return result

    monkeypatch.setattr(RobotState, "disconnect_stop_plan", disconnect_stop_plan)

    def t2_body() -> None:
        try:
            drv.disconnect()
        except BaseException as exc:  # noqa: BLE001 — наблюдение, попадёт в сообщение
            box["t2_error"] = repr(exc)

    t2 = threading.Thread(target=t2_body, name="t53h-H9-T2", daemon=True)
    try:
        t2.start()
        assert t2_entered.wait(_ENTER_S), "H9: окно недостижимо — T2 не дошёл до disconnect_stop_plan"
        soft_before = client.soft_count()
        box["connect"] = _bounded(drv.connect, _HANG_S, "connect")
        t2_release.set()
        t2.join(_JOIN_S)
        assert not t2.is_alive(), f"H9: disconnect не вернулся за {_JOIN_S} с"
        observed = {
            "connect": box["connect"],
            "soft": client.soft_count() - soft_before,
            "is_connected": drv.is_connected,
        }
    finally:
        t2_release.set()
        _teardown(drv)
    assert observed == {"connect": True, "soft": 1, "is_connected": False}, f"H9: {observed}; {box}"


# --------------------------------------------------------------------------------------------------
# H10 — путь тика: _note_reconnect_failed при disconnect посреди переподключения
# --------------------------------------------------------------------------------------------------


def _tick_window(drv: RobotDriverV2, client: _FakeClient, stop: Callable[[], None], window: str) -> dict[str, Any]:
    """T1 — ``tick()`` (переподключение тика), пауза в ``probe``; T2 — ``stop``; наблюдение после join T1."""
    drv.desired_connected = True
    drv.max_reconnect_attempts = 1
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    box: dict[str, Any] = {}

    def t1_body() -> None:
        try:
            drv.tick()
        except BaseException as exc:  # noqa: BLE001 — наблюдение
            box["tick_error"] = repr(exc)

    t1 = threading.Thread(target=t1_body, name=f"t53h-{window}-T1-tick", daemon=True)
    barrier.t1 = t1
    try:
        t1.start()
        assert barrier.entered.wait(_ENTER_S), f"{window}: окно недостижимо — тик не дошёл до probe; {box}"
        _bounded(stop, _HANG_S, "stop")
        inside = t1.is_alive() and not barrier.release_timed_out
        barrier.release.set()
        t1.join(_JOIN_S)
        assert not t1.is_alive(), f"{window}: tick() не вернулся за {_JOIN_S} с"
        assert inside, f"{window}: disconnect прошёл не внутри окна"
        return {
            "reconnect_exhausted": drv.reconnect_exhausted,
            "desired_connected": drv.desired_connected,
            "is_connected": drv.is_connected,
            **box,
        }
    finally:
        barrier.release.set()
        _teardown(drv)


def test_h10_a_plugin_order_not_counted_as_failed_reconnect() -> None:
    """Порядок плагина (``plugin.py:449-452``): ``desired_connected = False`` до ``disconnect``."""
    drv, client = _make_driver(connected=False)

    def stop() -> None:
        drv.desired_connected = False
        drv.disconnect()

    obs = _tick_window(drv, client, stop, "H10a")
    observed = {k: obs[k] for k in ("reconnect_exhausted", "desired_connected", "is_connected")}
    assert observed == {"reconnect_exhausted": False, "desired_connected": False, "is_connected": False}, f"{obs}"


def test_h10_b_direct_disconnect_counted_as_failed_reconnect() -> None:
    """Факт (не решение): ``disconnect`` без смены ``desired_connected`` — отказ считается неудачной попыткой."""
    drv, client = _make_driver(connected=False)
    obs = _tick_window(drv, client, drv.disconnect, "H10b")
    observed = {k: obs[k] for k in ("reconnect_exhausted", "desired_connected", "is_connected")}
    assert observed == {"reconnect_exhausted": True, "desired_connected": False, "is_connected": False}, f"{obs}"
