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
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2, RobotState
from Services.device_hub.tests.test_robot_v2_t53g_windows import (
    _ENTER_S,
    _HANG_S,
    _JOIN_S,
    _STOP_DEADLINE_S,
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


def _tick_window(
    drv: RobotDriverV2,
    client: _FakeClient,
    stop: Callable[[], None],
    window: str,
    *,
    barrier: _Barrier | None = None,
    released_by_stop: bool = False,
) -> dict[str, Any]:
    """T1 — ``tick()`` (переподключение тика), пауза в ``probe`` (или в своей точке ``barrier``); T2 — ``stop``.

    ``released_by_stop`` — барьер отпускает сам ``stop`` (T1 уже вышел). Наблюдение — после join T1, до уборки.
    """
    drv.desired_connected = True
    drv.max_reconnect_attempts = 1
    if barrier is None:
        barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    soft_before = client.soft_count()
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
        if released_by_stop:
            inside = barrier.release.is_set() and not barrier.release_timed_out
        else:
            inside = t1.is_alive() and not barrier.release_timed_out
        barrier.release.set()
        t1.join(_JOIN_S)
        assert not t1.is_alive(), f"{window}: tick() не вернулся за {_JOIN_S} с"
        assert inside, f"{window}: disconnect прошёл не внутри окна"
        return {
            "reconnect_exhausted": drv.reconnect_exhausted,
            "desired_connected": drv.desired_connected,
            "is_connected": drv.is_connected,
            "soft": client.soft_count() - soft_before,
            "levels": client.levels(),
            "probes": client.probes,
            "servo_calls": list(client.servo_calls),
            "transport_open": client.transport.is_connected,
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


# --------------------------------------------------------------------------------------------------
# Итерация 2 (стадия 0): H13 — повторная проверка desired_connected; H14–H17 — три потока connect / disconnect /
# request_stop. T3 — request_stop в своём daemon-потоке; если T2 держит _jog_tx_lock (обёртка disconnect_stop_plan),
# T3 ждёт замок до срока и пишет без него (В1) — так порядок достижим.
# --------------------------------------------------------------------------------------------------


def _start_t3(drv: RobotDriverV2, window: str, box: dict[str, Any]) -> threading.Thread:
    def body() -> None:
        try:
            drv.request_stop(deadline=time.monotonic() + _STOP_DEADLINE_S)
        except BaseException as exc:  # noqa: BLE001 — наблюдение
            box["t3_error"] = repr(exc)

    t3 = threading.Thread(target=body, name=f"t53h-{window}-T3", daemon=True)
    t3.start()
    return t3


def _is_t2(window: str) -> bool:
    return threading.current_thread().name == f"t53g-{window}-T2"  # имя потока _bounded


def _three_threads(
    drv: RobotDriverV2, client: _FakeClient, barrier: _Barrier, window: str, box: dict[str, Any]
) -> dict[str, Any]:
    """T1 — ``connect()`` до барьера в probe; T2 — ``disconnect()`` (его обёртки ведут T1 и T3); SOFT всего."""
    result: dict[str, Any] = {}

    def t1_body() -> None:
        try:
            result["connect"] = drv.connect()
        except BaseException as exc:  # noqa: BLE001 — наблюдение
            result["connect"] = repr(exc)

    t1 = threading.Thread(target=t1_body, name=f"t53h-{window}-T1-connect", daemon=True)
    barrier.t1 = t1
    soft_before = client.soft_count()
    try:
        t1.start()
        assert barrier.entered.wait(_ENTER_S), f"{window}: окно недостижимо — T1 не дошёл до probe"
        _bounded(drv.disconnect, _HANG_S, f"{window}-T2")
        barrier.release.set()
        t1.join(_JOIN_S)
        assert not t1.is_alive(), f"{window}: connect() не вернулся за {_JOIN_S} с"
        flags = [v for k, v in box.items() if k.endswith(("_before_d2", "_before_d3", "_begun", "_waited_d2"))]
        return {
            "soft": client.soft_count() - soft_before,
            "connect": result.get("connect"),
            "order_ok": bool(flags) and all(flags) and "t3_error" not in box,
        }
    finally:
        barrier.release.set()
        _teardown(drv)


def test_h13_tick_rechecks_desired_after_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """П. 6 (I1): тик прошёл ``desired_connected`` и стоит; «Отключить» отработало целиком; тик не подключается."""
    drv, client = _make_driver(connected=False, servo_tlm=0)
    barrier = _Barrier()
    original = RobotState.activity_alive

    def activity_alive(self: RobotState) -> bool:
        result = original(self)
        barrier.pause_if_t1()  # пауза только в T1 (тик): между проверкой desired и захватом _param_lock
        return result

    monkeypatch.setattr(RobotState, "activity_alive", activity_alive)

    def stop() -> None:
        drv.desired_connected = False  # порядок плагина: desired до disconnect
        drv.disconnect()

    obs = _tick_window(drv, client, stop, "H13", barrier=barrier)
    observed = {k: obs[k] for k in ("probes", "servo_calls", "levels")}
    assert observed == {"probes": 0, "servo_calls": [], "levels": []}, f"H13: {observed}; {obs}"


def test_h14_request_stop_snapshot_survives_disconnect_stop_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """П. 1: T1 в probe; T2 D1; T3 request_stop_begin; T1 выходит; T2 D2; T3 план; T2 D3 -> ровно 1 SOFT."""
    drv, client = _make_driver()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    box: dict[str, Any] = {}
    t3_begun = threading.Event()
    d2_done = threading.Event()
    holder: dict[str, threading.Thread] = {}
    orig_rsb = RobotState.request_stop_begin
    orig_db = RobotState.disconnect_begin
    orig_dsp = RobotState.disconnect_stop_plan

    def request_stop_begin(self: RobotState) -> None:
        orig_rsb(self)
        if threading.current_thread().name == "t53h-H14-T3":
            t3_begun.set()
            box["t3_waited_d2"] = d2_done.wait(_JOIN_S)  # план T3 — после D2

    def disconnect_begin(self: RobotState) -> bool:
        result = orig_db(self)
        if _is_t2("H14"):
            holder["t3"] = _start_t3(drv, "H14", box)
            box["t3_begun"] = t3_begun.wait(_ENTER_S)
            barrier.release.set()
            assert barrier.t1 is not None
            barrier.t1.join(_JOIN_S)
            box["t1_exited_before_d2"] = not barrier.t1.is_alive()
        return result

    def disconnect_stop_plan(self: RobotState, *args: Any, **kwargs: Any) -> Any:
        result = orig_dsp(self, *args, **kwargs)
        if _is_t2("H14"):
            d2_done.set()
            holder["t3"].join(_JOIN_S)
            box["t3_exited_before_d3"] = not holder["t3"].is_alive()
        return result

    monkeypatch.setattr(RobotState, "request_stop_begin", request_stop_begin)
    monkeypatch.setattr(RobotState, "disconnect_begin", disconnect_begin)
    monkeypatch.setattr(RobotState, "disconnect_stop_plan", disconnect_stop_plan)
    obs = _three_threads(drv, client, barrier, "H14", box)
    assert obs == {"soft": 1, "connect": False, "order_ok": True}, f"H14: {obs}; {box}"


def test_h15_request_stop_between_disconnect_sections_keeps_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """П. 2, второй случай: T1 в probe; T2 D2; T1 выходит; T3 request_stop целиком; T2 D3 -> ровно 1 SOFT."""
    drv, client = _make_driver()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    box: dict[str, Any] = {}
    orig_dsp = RobotState.disconnect_stop_plan

    def disconnect_stop_plan(self: RobotState, *args: Any, **kwargs: Any) -> Any:
        result = orig_dsp(self, *args, **kwargs)
        if _is_t2("H15"):
            barrier.release.set()
            assert barrier.t1 is not None
            barrier.t1.join(_JOIN_S)
            box["t1_exited_before_d3"] = not barrier.t1.is_alive()
            t3 = _start_t3(drv, "H15", box)
            t3.join(_JOIN_S)
            box["t3_exited_before_d3"] = not t3.is_alive()
        return result

    monkeypatch.setattr(RobotState, "disconnect_stop_plan", disconnect_stop_plan)
    obs = _three_threads(drv, client, barrier, "H15", box)
    assert obs == {"soft": 1, "connect": False, "order_ok": True}, f"H15: {obs}; {box}"


def test_h16_tick_refused_by_disconnect_one_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """П. 2 (H5-tick): тик в probe; «Отключить» D1, D2; тик отказывает и выходит; D3 -> 1 SOFT; сокет закрыт."""
    drv, client = _make_driver()
    barrier = _Barrier()
    box: dict[str, Any] = {}
    orig_dsp = RobotState.disconnect_stop_plan

    def disconnect_stop_plan(self: RobotState, *args: Any, **kwargs: Any) -> Any:
        result = orig_dsp(self, *args, **kwargs)
        if threading.current_thread() is not barrier.t1 and barrier.entered.is_set() and not barrier.release.is_set():
            barrier.release.set()
            assert barrier.t1 is not None
            barrier.t1.join(_JOIN_S)  # тик выходит из connect (отказ) и делает свой хвост до D3
            box["tick_exited_before_d3"] = not barrier.t1.is_alive()
        return result

    monkeypatch.setattr(RobotState, "disconnect_stop_plan", disconnect_stop_plan)

    def stop() -> None:
        drv.desired_connected = False
        drv.disconnect()

    obs = _tick_window(drv, client, stop, "H16", barrier=barrier, released_by_stop=True)
    observed = {"soft": obs["soft"], "transport_open": obs["transport_open"], **box}
    assert observed == {"soft": 1, "transport_open": False, "tick_exited_before_d3": True}, f"H16: {obs}"


def test_h17_request_stop_inside_disconnect_one_soft_total(monkeypatch: pytest.MonkeyPatch) -> None:
    """П. 3 (защёлка): робот подключён; T2 стоит после D2; T3 request_stop целиком; T2 D3 -> всего 1 SOFT."""
    drv, client = _make_driver()
    box: dict[str, Any] = {}
    orig_dsp = RobotState.disconnect_stop_plan

    def disconnect_stop_plan(self: RobotState, *args: Any, **kwargs: Any) -> Any:
        result = orig_dsp(self, *args, **kwargs)
        if _is_t2("H17"):
            t3 = _start_t3(drv, "H17", box)
            t3.join(_JOIN_S)
            box["t3_exited_before_d3"] = not t3.is_alive()
        return result

    try:
        assert _bounded(drv.connect, _JOIN_S, "H17 connect") is True, "H17: робот не подключился (настройка теста)"
        monkeypatch.setattr(RobotState, "disconnect_stop_plan", disconnect_stop_plan)
        soft_before = client.soft_count()
        _bounded(drv.disconnect, _HANG_S, "H17-T2")
        observed = {"soft": client.soft_count() - soft_before, **box}
    finally:
        monkeypatch.undo()
        _teardown(drv)
    assert observed == {"soft": 1, "t3_exited_before_d3": True}, f"H17: {observed}"


def test_h18_ready_robot_dropped_link_tick_no_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    """Стадия 0 р.2 (сценарий ревьюера): готовый робот, связь упала вне тика (``_ready`` True). Тик стоит после
    ``connect_begin`` -> ("go", True); «Отключить» целиком; тик открывает сокет в C3, отказывает в C4 -> сокет закрыт,
    SOFT нет (связи в D2 не было)."""
    drv, client = _make_driver()
    assert _bounded(drv.connect, _HANG_S, "H18 предварительный connect") is True, "H18: робот не подключился до T1"
    client.transport.is_connected = False  # обрыв вне тика: готовность осталась
    barrier = _Barrier()
    box: dict[str, Any] = {}
    original = RobotState.connect_begin

    def connect_begin(self: RobotState) -> tuple[str, bool]:
        result = original(self)
        box.setdefault("connect_begin", result)
        barrier.pause_if_t1()
        return result

    monkeypatch.setattr(RobotState, "connect_begin", connect_begin)

    def stop() -> None:
        drv.desired_connected = False
        drv.disconnect()

    obs = _tick_window(drv, client, stop, "H18", barrier=barrier)
    observed = {"soft": obs["soft"], "transport_open": obs["transport_open"], "connect_begin": box.get("connect_begin")}
    assert observed == {"soft": 0, "transport_open": False, "connect_begin": ("go", True)}, f"H18: {obs}"


# --------------------------------------------------------------------------------------------------
# H12 (I6) — связь поднята между D1 (disconnect_begin) и D2 (disconnect_stop_plan): снимок в D2, не в D1
# --------------------------------------------------------------------------------------------------


def test_h12_link_up_between_disconnect_sections_one_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """T1 стоит в ``transport.connect`` (до A3, как H6); T2 после D1 отпускает T1 и ждёт, пока T1 поднимет связь и
    встанет в ``probe`` (второй барьер); T2 идёт в D2 и D3 -> ровно 1 SOFT; второй барьер отпускает тест после
    возврата ``disconnect``."""
    drv, client = _make_driver(connected=False)
    barrier = _Barrier()
    client.transport.on_connect = barrier.pause_if_t1
    probe_entered = threading.Event()
    probe_release = threading.Event()
    box: dict[str, Any] = {}

    def second_barrier() -> None:
        if threading.current_thread() is barrier.t1:
            probe_entered.set()
            box["probe_released"] = probe_release.wait(_JOIN_S)

    client.on_probe = second_barrier
    original = RobotState.disconnect_begin

    def disconnect_begin(self: RobotState) -> bool:
        result = original(self)
        if threading.current_thread() is not barrier.t1 and not barrier.release.is_set():
            barrier.release.set()  # T1 выходит из transport.connect: связь поднимается ПОСЛЕ D1
            box["t1_in_probe"] = probe_entered.wait(_ENTER_S)
            assert box["t1_in_probe"], "H12: T1 не дошёл до probe за дедлайн (находка, не таймаут теста)"
        return result

    monkeypatch.setattr(RobotState, "disconnect_begin", disconnect_begin)

    def stop() -> None:
        try:
            drv.disconnect()
        finally:
            probe_release.set()

    try:
        obs = _observe(drv, client, barrier, "H12", stop=stop, released_by_stop=True)
    finally:
        probe_release.set()
    observed = {"soft": obs["soft_during_stop"], "connect": obs["connect"], "t1_in_probe": box.get("t1_in_probe")}
    assert observed == {"soft": 1, "connect": False, "t1_in_probe": True}, f"H12: {observed}; {obs}"


# --------------------------------------------------------------------------------------------------
# H19 — остаток ADR-DH-011: request_stop целиком после решения D3 (до D6) даёт второй SOFT
# --------------------------------------------------------------------------------------------------


def test_h19_request_stop_after_d3_decision_second_soft_residue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Фиксирует ИМЕНОВАННЫЙ ОСТАТОК, а не желаемое свойство: T1 в probe (связь поднята), T2 прошёл D3 (1 SOFT),
    T3 целиком ``request_stop`` на входе D4 (до D6). ``request_stop_begin`` открывает новое поколение защёлки
    (ADR-DH-009), снимок монотонен, а ``link_up()`` True до D6 -> второй SOFT, как у подключённого робота на main.
    ``connect`` False, ``is_connected`` False, сокет закрыт хвостом ``disconnect``. 1 SOFT при любом порядке — отдельная
    задача и решение владельца."""
    drv, client = _make_driver()
    barrier = _Barrier()
    client.on_probe = barrier.pause_if_t1
    box: dict[str, Any] = {}
    t2_name = "t53g-H19-T2"
    original = RobotState.threads_to_close

    def threads_to_close(self: RobotState) -> Any:
        if threading.current_thread().name == t2_name and "t3_done" not in box:

            def body() -> None:
                try:
                    drv.request_stop(deadline=time.monotonic() + _STOP_DEADLINE_S)
                except BaseException as exc:  # noqa: BLE001 — наблюдение: попадёт в отчёт
                    box["t3_err"] = repr(exc)

            t3 = threading.Thread(target=body, name="t53h-H19-T3", daemon=True)
            t3.start()
            t3.join(_JOIN_S)
            box["t3_done"] = not t3.is_alive()
        return original(self)

    monkeypatch.setattr(RobotState, "threads_to_close", threads_to_close)
    result: dict[str, Any] = {}

    def t1_body() -> None:
        result["connect"] = drv.connect()

    t1 = threading.Thread(target=t1_body, name="t53h-H19-T1", daemon=True)
    barrier.t1 = t1
    try:
        t1.start()
        assert barrier.entered.wait(_ENTER_S), "H19: окно недостижимо — T1 не дошёл до probe"
        soft_before = client.soft_count()
        _bounded(drv.disconnect, _HANG_S, "H19-T2")
        soft = client.soft_count() - soft_before
        barrier.release.set()
        t1.join(_JOIN_S)
        assert not t1.is_alive(), "H19: connect() не вернулся после release"
        observed = {"soft": soft, "connect": result.get("connect"), "is_connected": drv.is_connected}
        assert box.get("t3_done") is True and "t3_err" not in box, f"H19: T3 не отработал: {box}"
        assert observed == {"soft": 2, "connect": False, "is_connected": False}, f"H19: {observed}; {box}"
        assert client.transport.is_connected is False, "H19: сокет не закрыт хвостом disconnect"
    finally:
        barrier.release.set()
        monkeypatch.undo()
        _teardown(drv)
