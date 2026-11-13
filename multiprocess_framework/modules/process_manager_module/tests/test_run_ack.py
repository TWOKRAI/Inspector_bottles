# -*- coding: utf-8 -*-
"""Task 1.7 (system-run-state) — слепые приёмочные тесты квитирования аварии ``system.run.ack`` (10 функций).

Написано ДО реализации по наблюдаемым требованиям брифа (DESIGN/FILES, ``plans/**`` и отчёты не читались).

Контракт (из брифа): после аварии (потеря готовности в ``running`` -> ``fault``, Task 1.3; остановка процессов в
аварии, Task 1.4) система стоит в ``fault``, пока оператор не квитирует. Команда PM ``system.run.ack`` (быстрая, без
ожиданий): в ``fault`` при завершённой остановке -> ``{"success": True, "state": "ready"|"not_ready"}`` по оценке
готовности; пока остановка не завершена -> отказ ``fault_stopping``; вне ``fault`` -> ``no_fault``, в
``shutting_down`` -> ``shutting_down``. ``last_fault.acknowledged_at`` = ``time.time()`` момента ack; ``last_fault``
живёт до следующего УСПЕШНОГО START (тогда ``None``). Публикуемое поле ``ack_allowed`` (рядом с ``start_allowed``):
True только в ``fault`` при завершённой остановке. START в ``fault`` отказан ``fault_unacknowledged`` с причинами
``last_fault``; STOP в ``fault`` — no-op; ``system.shutdown`` из ``fault`` проходит без ``ack``.

Обвязка — настоящие объекты, как в ``test_run_stop.py`` (``_Rig``: ``ProcessManagerProcess`` + ``ProcessMonitor`` +
двойник детей ``_ChildSim``, такт ``monitor._run_iteration()``) и ``test_run_commands.py`` (``make_run_pm``,
``_Store``). Ожидаемые значения — литералы. Всё, что может зависнуть, — в daemon-потоке с join-дедлайном.

Допущения тестера (полный список — в отчёте):
  * обработчик команды берётся по ИМЕНИ команды: ``pm._register_builtin_commands()`` на ``MagicMock`` менеджера
    команд, из вызовов ``register_command`` берётся обработчик ``"system.run.ack"`` (имя метода не важно);
    вызывается без аргументов, как ``_cmd_system_run_stop()``; регистрация — без ``executor`` (класс R, быстрая);
  * ответ — ``dict`` с ключами ``success`` / ``state`` / ``error`` (``error`` у успеха — ``None`` или отсутствует);
    остальные ключи ответа не сверяются;
  * ``ack_allowed`` читается из ``pm._cmd_system_run_status()`` и из стора по пути ``system.run.ack_allowed``;
  * при ``ack`` готовность оценивается заново или берётся с последнего такта — тесты подводят оба источника к
    одному ответу (перед ``ack`` — heartbeat детей и такт монитора).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

from .test_run_commands import _Store, make_run_pm
from .test_run_stop import _DEADLINE_S, _Rig, _bounded, _fault_stop_done, _wait

# причина аварии, которую шлёт «cam» (литерал: форма листа readiness, как её отдают плагины)
_FAILURE = {"severity": "failure", "source": "plugin", "node": "cam", "message": "cam: failure"}


@pytest.fixture
def rig_factory():
    rigs: list[_Rig] = []

    def make(*args: Any, **kwargs: Any) -> _Rig:
        rig = _Rig(*args, **kwargs)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        rig.close()


# --------------------------------------------------------------------------- #
# Хелперы
# --------------------------------------------------------------------------- #


def _ack_handler(pm: Any) -> Callable[..., dict]:
    """Обработчик команды ``system.run.ack``, как его регистрирует PM; нет регистрации — упавший ассерт."""
    pm.command_manager = MagicMock()
    pm._register_builtin_commands()
    for call in pm.command_manager.register_command.call_args_list:
        if call.args and call.args[0] == "system.run.ack":
            return call.args[1]
    pytest.fail("команда system.run.ack не зарегистрирована в _register_builtin_commands")


def _ack(pm: Any) -> dict:
    """``system.run.ack`` в daemon-потоке с дедлайном: быстрая команда не должна блокировать вызывающего."""
    reply = _bounded(_ack_handler(pm), _DEADLINE_S)
    assert isinstance(reply, dict), reply
    return reply


def _assert_accepted(reply: dict, state: str) -> None:
    assert reply.get("success") is True, reply
    assert reply.get("state") == state, reply
    assert reply.get("error") is None, reply


def _assert_refused(reply: dict, error: str) -> None:
    assert reply.get("success") is False, reply
    assert reply.get("error") == error, reply


def _attach_store(pm: Any) -> _Store:
    store = _Store()
    pm._state_store_manager = store
    return store


def _to_fault(rig: _Rig, *, wait_done: bool = True) -> None:
    """``running`` -> потеря готовности (``cam`` с ``failure``) -> такт -> ``fault``; ждём конец остановки в аварии."""
    rig.to_running()
    rig.sim.set("cam", ready=False, reasons=[_FAILURE])
    rig.sim.beat_now()
    rig.tick()
    assert rig.state == "fault"
    if wait_done:
        assert _wait(lambda: _fault_stop_done(rig.pm) is True, 5.0), "остановка в аварии не завершилась"


def _recover(rig: _Rig) -> None:
    """``cam`` снова готов: heartbeat + такт монитора (в ``fault`` такт состояние не меняет)."""
    rig.sim.set("cam", ready=True, reasons=[])
    rig.sim.beat_now()
    rig.tick()


def _assert_ack_allowed(pm: Any, store: _Store | None, expected: bool) -> None:
    """``ack_allowed`` и в ответе статуса, и в сторе (последнее записанное значение) равен ``expected``."""
    if expected:
        assert _wait(lambda: pm._cmd_system_run_status().get("ack_allowed") is True, 5.0), pm._cmd_system_run_status()
    assert pm._cmd_system_run_status().get("ack_allowed") is expected, pm._cmd_system_run_status()
    if store is not None:
        if expected:
            assert _wait(lambda: store.values("system.run.ack_allowed")[-1:] == [True], 5.0), store.writes
        assert store.values("system.run.ack_allowed")[-1:] == [expected], store.writes


def _is_time(value: Any, lo: float, hi: float) -> bool:
    return isinstance(value, float) and lo <= value <= hi


# --------------------------------------------------------------------------- #
# 1. ack в fault после остановки -> ready; регистрация; acknowledged_at; ack_allowed
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_ack_in_fault_after_stop_goes_ready(rig_factory) -> None:
    """Авария, остановка завершена, готовность вернулась: ``ack`` -> ``{"success": True, "state": "ready"}``. Команда
    зарегистрирована быстрой (без ``executor``). ``ack_allowed`` до ack True, после False (статус и стор);
    ``start_allowed`` после True; ``last_fault.acknowledged_at`` — время ack."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    store = _attach_store(rig.pm)
    _to_fault(rig)
    _recover(rig)
    _assert_ack_allowed(rig.pm, store, True)
    assert rig.status()["start_allowed"] is False

    registered = [c for c in _registered_calls(rig.pm) if c.args[0] == "system.run.ack"]
    assert len(registered) == 1, "system.run.ack зарегистрирована не ровно один раз"
    assert "executor" not in registered[0].kwargs, registered[0].kwargs

    t0 = time.time()
    reply = _ack(rig.pm)
    t1 = time.time()

    _assert_accepted(reply, "ready")
    status = rig.status()
    assert status["state"] == "ready", status
    assert status["start_allowed"] is True, status
    _assert_ack_allowed(rig.pm, store, False)
    assert status["last_fault"] is not None, status
    assert _is_time(status["last_fault"]["acknowledged_at"], t0, t1), status["last_fault"]


def _registered_calls(pm: Any) -> list:
    pm.command_manager = MagicMock()
    pm._register_builtin_commands()
    return [c for c in pm.command_manager.register_command.call_args_list if c.args]


# --------------------------------------------------------------------------- #
# 2. ack при сохраняющейся failure -> not_ready
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_ack_in_fault_with_failure_goes_not_ready(rig_factory) -> None:
    """Авария, остановка завершена, ``cam`` всё ещё с ``failure``: ``ack`` принят, но итог ``not_ready`` (а не
    ``ready``); START отказан, причина ``cam`` в ``reasons``; ``ack_allowed`` False."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    store = _attach_store(rig.pm)
    _to_fault(rig)
    rig.tick()  # такт в fault: оценка «не готов» учтена, состояние то же
    assert rig.state == "fault"

    t0 = time.time()
    reply = _ack(rig.pm)
    t1 = time.time()

    _assert_accepted(reply, "not_ready")
    status = rig.status()
    assert status["state"] == "not_ready", status
    assert status["start_allowed"] is False, status
    assert [r["node"] for r in status["reasons"] if r["severity"] == "failure"] == ["cam"], status["reasons"]
    _assert_ack_allowed(rig.pm, store, False)
    assert _is_time(status["last_fault"]["acknowledged_at"], t0, t1), status["last_fault"]


# --------------------------------------------------------------------------- #
# 3. ack до конца остановки -> fault_stopping
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_ack_before_stop_done_refused_fault_stopping(rig_factory) -> None:
    """``plc`` не подтверждает ``paused`` (срок 10 с не вышел): остановка в аварии не завершена. ``ack`` ->
    ``fault_stopping``, состояние ``fault``, ``ack_allowed`` False, ``acknowledged_at`` пуст. Когда ``plc`` подтвердил
    и остановка завершилась — ``ack_allowed`` True и тот же ``ack`` проходит."""
    rig = rig_factory(("cam", "plc"), timeout_s=10.0)
    store = _attach_store(rig.pm)
    gate = threading.Event()
    rig.sim.set("plc", gate=gate)
    _to_fault(rig, wait_done=False)
    _recover(rig)
    time.sleep(0.2)  # последовательность остановки в аварии идёт и ждёт plc
    assert _fault_stop_done(rig.pm) is not True, "остановка завершилась, хотя plc не подтвердил paused"

    reply = _ack(rig.pm)

    _assert_refused(reply, "fault_stopping")
    status = rig.status()
    assert status["state"] == "fault", status
    assert status["last_fault"]["acknowledged_at"] is None, status["last_fault"]
    _assert_ack_allowed(rig.pm, store, False)

    gate.set()  # plc подтверждает паузу
    assert _wait(lambda: _fault_stop_done(rig.pm) is True, 5.0), "остановка в аварии не завершилась"
    _assert_ack_allowed(rig.pm, store, True)
    _assert_accepted(_ack(rig.pm), "ready")


# --------------------------------------------------------------------------- #
# 4. ack вне fault
# --------------------------------------------------------------------------- #


def _pm_in_state(state: str) -> Any:
    """PM без детей в нужном состоянии (``make_run_pm`` + прямые события машины)."""
    pm = make_run_pm(True, boot=state != "booting")
    if state == "not_ready":
        pm._run_apply("tick", ready=False)
    elif state == "running":
        assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    elif state == "stopping":
        assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
        pm._run_apply("stop")  # последовательность не запускаем: состояние остаётся stopping
    elif state == "shutting_down":
        pm._run_apply("shutdown")
    assert pm._run_snapshot()[0].value == state
    return pm


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("state", "error"),
    [
        ("booting", "no_fault"),
        ("not_ready", "no_fault"),
        ("ready", "no_fault"),
        ("running", "no_fault"),
        ("stopping", "no_fault"),
        ("shutting_down", "shutting_down"),
    ],
)
def test_ack_outside_fault_refused_no_fault(state: str, error: str) -> None:
    """Вне ``fault`` ``ack`` отказан (``no_fault``; в ``shutting_down`` — ``shutting_down``), состояние не меняется,
    ``ack_allowed`` False, ``last_fault`` остаётся пустым; в ``running`` событие работы остаётся взведённым."""
    pm = _pm_in_state(state)
    store = _attach_store(pm)
    event_before = pm._run_event.is_set()

    reply = _ack(pm)

    _assert_refused(reply, error)
    status = pm._cmd_system_run_status()
    assert status["state"] == state, status
    assert status["last_fault"] is None, status
    _assert_ack_allowed(pm, store, False)
    assert pm._run_event.is_set() is event_before


# --------------------------------------------------------------------------- #
# 5. Повторный ack
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_ack_twice_second_refused_no_fault(rig_factory) -> None:
    """Второй ``ack`` после успешного: состояние уже не ``fault`` -> ``no_fault``; состояние ``ready`` и
    ``acknowledged_at`` первого ack не меняются."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    _to_fault(rig)
    _recover(rig)
    _assert_accepted(_ack(rig.pm), "ready")
    first = rig.status()["last_fault"]["acknowledged_at"]
    assert isinstance(first, float), first

    second = _ack(rig.pm)

    _assert_refused(second, "no_fault")
    status = rig.status()
    assert status["state"] == "ready", status
    assert status["last_fault"]["acknowledged_at"] == first, status["last_fault"]


# --------------------------------------------------------------------------- #
# 6. STOP в fault — no-op
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_in_fault_noop(rig_factory) -> None:
    """``system.run.stop`` в ``fault`` (при настроенном шаге ``pre_stop``): no-op — не принят, шагов нет, состояние
    ``fault``, событие не взведено, ``ack_allowed`` остаётся True, ``last_fault`` не тронут; ``ack`` после проходит."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True)
    store = _attach_store(rig.pm)
    _to_fault(rig)
    _recover(rig)
    _assert_ack_allowed(rig.pm, store, True)
    fault_before = rig.status()["last_fault"]

    reply = rig.stop()

    assert reply.get("accepted") is not True, reply
    status = rig.status()
    assert status["state"] == "fault", status
    assert status["last_fault"] == fault_before, status["last_fault"]
    assert rig.router.requests == [], f"STOP в fault исполнил шаги pre_stop: {rig.router.requests}"
    assert rig.pm._run_event.is_set() is False
    _assert_ack_allowed(rig.pm, store, True)
    _assert_accepted(_ack(rig.pm), "ready")


# --------------------------------------------------------------------------- #
# 7. START в fault отказан
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_start_in_fault_refused_unacknowledged_with_reasons(rig_factory) -> None:
    """START в ``fault``: ``fault_unacknowledged``, в ответе причины аварии (``cam`` с ``failure``), состояние
    ``fault``, событие не взведено. Отказанный START не расходует ``ack``: он по-прежнему разрешён и проходит."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    store = _attach_store(rig.pm)
    _to_fault(rig)

    reply = rig.pm._cmd_system_run_start()

    _assert_refused(reply, "fault_unacknowledged")
    assert reply.get("state") == "fault", reply
    assert reply.get("reasons") == [_FAILURE], reply
    assert rig.state == "fault"
    assert rig.pm._run_event.is_set() is False
    _assert_ack_allowed(rig.pm, store, True)

    _recover(rig)
    _assert_accepted(_ack(rig.pm), "ready")


# --------------------------------------------------------------------------- #
# 8. last_fault живёт до успешного START
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_last_fault_kept_after_ack_until_start(rig_factory) -> None:
    """После ``ack`` (итог ``not_ready``) ``last_fault`` с ``acknowledged_at`` остаётся и в статусе, и в листе стора
    ``system.run.last_fault``; не стирается ни отказанным START, ни тактом готовности. Успешный START (после того как
    готовность вернулась) -> ``last_fault`` = None (статус и стор)."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    store = _attach_store(rig.pm)
    _to_fault(rig)
    t0 = time.time()
    _assert_accepted(_ack(rig.pm), "not_ready")
    t1 = time.time()

    status = rig.status()
    acked = status["last_fault"]["acknowledged_at"]
    assert _is_time(acked, t0, t1), status["last_fault"]
    assert status["last_fault"]["reasons"] == [_FAILURE], status["last_fault"]
    assert store.values("system.run.last_fault")[-1]["acknowledged_at"] == acked, store.writes

    refused = rig.pm._cmd_system_run_start()
    _assert_refused(refused, "not_ready")
    assert rig.status()["last_fault"]["acknowledged_at"] == acked

    _recover(rig)  # такт: not_ready -> ready
    assert rig.state == "ready"
    assert rig.status()["last_fault"]["acknowledged_at"] == acked
    assert store.values("system.run.last_fault")[-1]["acknowledged_at"] == acked, store.writes

    assert rig.pm._cmd_system_run_start() == {"success": True, "state": "running"}
    assert rig.status()["last_fault"] is None, rig.status()
    assert store.values("system.run.last_fault")[-1] is None, store.writes


# --------------------------------------------------------------------------- #
# 9. system.shutdown из fault без ack
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_shutdown_from_fault_without_ack(rig_factory) -> None:
    """``system.shutdown`` из ``fault`` проходит без ``ack``: состояние -> ``shutting_down``, события останова
    взведены, авария не квитирована (``acknowledged_at`` пуст), ``ack_allowed`` False; ``ack`` теперь отказан
    ``shutting_down``."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    store = _attach_store(rig.pm)
    _to_fault(rig)
    _assert_ack_allowed(rig.pm, store, True)

    reply = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": "graceful"}), _DEADLINE_S)

    assert reply.get("accepted") is True, reply
    assert _wait(lambda: rig.state == "shutting_down", _DEADLINE_S), rig.state
    assert _wait(lambda: rig.pm._system_stop_event.is_set(), _DEADLINE_S), "события останова не взведены"
    status = rig.status()
    assert status["last_fault"]["acknowledged_at"] is None, status["last_fault"]
    _assert_ack_allowed(rig.pm, store, False)
    _assert_refused(_ack(rig.pm), "shutting_down")


# --------------------------------------------------------------------------- #
# 10. Гонка ack и завершения остановки в аварии; параллельные ack
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_ack_and_stop_done_race_one_winner(rig_factory) -> None:
    """24 круга ``ready -> running -> fault``: ``plc`` подтверждает ``paused`` (``gate.set()``) в потоке, одновременно
    два ``ack`` стартуют со сдвигом по окну опроса остановки (0..70 мс). В каждом круге: успешных ack не больше одного;
    остальные отказы — только ``fault_stopping`` (до конца остановки) либо ``no_fault`` (после чужого успеха);
    ``no_fault`` без успеха невозможен; «ack принят, а состояние fault» и двойной переход не бывают: по стору состояния
    круга ровно ``running -> fault -> ready``. Если оба ack опередили конец остановки — позднейший ack проходит."""
    rig = rig_factory(("cam", "plc"), timeout_s=30.0)
    store = _attach_store(rig.pm)
    handler = _ack_handler(rig.pm)
    outcomes: list[str] = []

    for i in range(24):
        gate = threading.Event()
        rig.sim.set("cam", ready=True, reasons=[])
        rig.sim.set("plc", gate=gate)
        rig.sim.beat_now()
        rig.tick()
        assert rig.state == "ready", f"круг {i}: перед стартом не ready: {rig.status()}"
        mark = len(store.values("system.run.state"))
        assert rig.pm._cmd_system_run_start() == {"success": True, "state": "running"}, f"круг {i}"
        rig.sim.set("cam", ready=False, reasons=[_FAILURE])
        rig.sim.beat_now()
        rig.tick()
        assert rig.state == "fault", f"круг {i}"
        rig.sim.set("cam", ready=True, reasons=[])
        rig.sim.beat_now()
        rig.tick()
        assert _fault_stop_done(rig.pm) is not True, f"круг {i}: остановка завершена до гонки"

        offset = i * 0.003
        replies: list[dict] = []
        lock = threading.Lock()
        barrier = threading.Barrier(3)

        def release() -> None:
            barrier.wait(_DEADLINE_S)
            gate.set()

        def acker(delay: float) -> None:
            barrier.wait(_DEADLINE_S)
            time.sleep(delay)
            result = handler()
            with lock:
                replies.append(result)

        threads = [
            threading.Thread(target=release, daemon=True, name="ack-race-release"),
            threading.Thread(target=acker, args=(offset,), daemon=True, name="ack-race-a"),
            threading.Thread(target=acker, args=(offset + 0.0015,), daemon=True, name="ack-race-b"),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join(_DEADLINE_S)
            assert not th.is_alive(), f"круг {i}: поток {th.name} завис"

        assert len(replies) == 2, f"круг {i}: {replies}"
        wins = [r for r in replies if r.get("success") is True]
        losses = [r for r in replies if r.get("success") is not True]
        assert len(wins) <= 1, f"круг {i}: два успешных ack: {replies}"
        for loss in losses:
            assert loss.get("success") is False and loss.get("error") in ("fault_stopping", "no_fault"), (i, loss)
            if loss.get("error") == "no_fault":
                assert wins, f"круг {i}: no_fault без успешного ack: {replies}"
        if wins:
            assert wins[0].get("state") == "ready", (i, wins[0])
            assert rig.state == "ready", f"круг {i}: ack принят, а состояние {rig.state}"
        else:
            assert rig.state == "fault", f"круг {i}: оба ack отказаны, а состояние {rig.state}"
            assert rig.status()["last_fault"]["acknowledged_at"] is None, f"круг {i}"
            assert _wait(lambda: _fault_stop_done(rig.pm) is True, 5.0), f"круг {i}: остановка не завершилась"
            _assert_accepted(handler(), "ready")
        outcomes.append("win" if wins else "late")

        assert store.values("system.run.state")[mark:] == ["running", "fault", "ready"], (
            f"круг {i}: переходы {store.values('system.run.state')[mark:]}"
        )
        assert isinstance(rig.status()["last_fault"]["acknowledged_at"], float), f"круг {i}"
        assert _fault_stop_done(rig.pm) is False, f"круг {i}: признак остановки не сброшен после ack"
    assert len(outcomes) == 24
