# -*- coding: utf-8 -*-
"""Task 1.9b — hazard-тесты автора H1-H4, H6-H9 (гонки, порядок, локи, один владелец стопа).

Спека — ``plans/lifecycle-stop-ownership/tasks/T1.9b_tests.md`` («Hazard-тесты автора»). H5 ушёл в Task 1.9c.
Обвязка — настоящий PM и настоящие spawn-дети слепого тестера (``Rig`` из ``test_lifecycle_fifo_acceptance``,
``LifecycleChild`` из ``_lifecycle_fifo_helpers``); здесь они только читаются. Ожидаемые значения — литералы.
Всё, что может блокироваться, ждёт с дедлайном (``pytest-timeout`` не установлен): ответы — через ``Rig.wait_reply``,
прямые вызовы команд — в daemon-потоке с ``join`` по дедлайну.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.command_module import DEFERRED

from ..core import process_registry as registry_module
from ..core.child_process_stop import ChildProcessStop
from . import test_lifecycle_fifo_acceptance as acceptance
from .test_lifecycle_fifo_acceptance import FAST_S, MID_STOP_S, Rig

SHUTDOWN_IDLE_S = 0.2  # H1: от отправки system.shutdown до простоя исполнителя
DIRECT_DEADLINE_S = 40.0  # потолок ожидания прямого вызова команды
H7_FILL_WIRES = 20_000  # H7: размер ``_active_wires`` — итерация по живому словарю должна длиться дольше кванта GIL


@pytest.fixture
def rig(tmp_path: Path):
    r = Rig(tmp_path)
    try:
        r.start()
        yield r
    finally:
        r.close()


class Direct:
    """Прямая дверь без очереди: ``command_manager.handle_command(msg, reply=...)`` из потока теста.

    Ответ приходит через ``reply`` (с потока исполнителя) или сразу (R/T-ветка на месте).
    """

    def __init__(self, rig: Rig, command: str, data: dict | None = None) -> None:
        self.result: Any = None
        self.thread_name: str | None = None
        self.done = threading.Event()
        self.t_start = time.monotonic()
        self.t_done: float | None = None
        message = {"command": command, "data": dict(data or {})}

        def reply(result: Any) -> None:
            self.result = result
            self.thread_name = threading.current_thread().name
            self.t_done = time.monotonic()
            self.done.set()

        def call() -> None:
            outcome = rig.pm.command_manager.handle_command(message, reply=reply)
            if not self.done.is_set() and outcome is not DEFERRED:
                reply(outcome)  # команда без исполнителя: результат вернулся синхронно

        self._thread = threading.Thread(target=call, daemon=True, name=f"direct-{command}")
        self._thread.start()

    def wait(self, timeout: float = DIRECT_DEADLINE_S) -> bool:
        return self.done.wait(timeout)

    @property
    def latency(self) -> float | None:
        return None if self.t_done is None else self.t_done - self.t_start


def _assert_in_transition(rig: Rig, name: str, what: str) -> None:
    """Предусловие «операция с ``name`` идёт», не ожидая лок под проверкой.

    ``_in_transition`` берёт ``_routing_lock``. Вызов на потоке теста при локе, взятом на всю операцию, ждал бы
    её конца, и проверка лока ниже шла бы по свободному локу (H3/H7 зелёные под И7, разбор
    ``docs/reviews/2026-10-26_task-1.9b-I7-debugger.md``). Поэтому — daemon-поток с дедлайном ``FAST_S``:
    не ответил вовремя — читатель класса R заблокирован, это уже красный.
    """
    box: dict[str, bool] = {}
    th = threading.Thread(
        target=lambda: box.__setitem__("value", rig.pm._in_transition(name)), daemon=True, name="in-transition"
    )
    th.start()
    th.join(FAST_S)
    assert not th.is_alive(), f"предусловие {what}: _in_transition('{name}') не ответил за {FAST_S} с — лок занят"
    assert box.get("value") is True, f"предусловие {what}: операция с '{name}' не идёт"


def _remove_slow_topology(rig: Rig) -> None:
    """Планировщик убирает только slow (стоп 3,0 с в ``topology.apply``)."""
    rig.pm._topology_manager.configure(
        diff_fn=lambda current, desired: {"has_changes": True},
        commands_fn=lambda diff, desired: [
            {"cmd": "process.stop_all", "process_names": ["slow"]},
            {"cmd": "process.cleanup", "process_name": "slow"},
        ],
    )


# --------------------------------------------------------------------------- #
# H1: системный стоп снимает исполнитель сразу
# --------------------------------------------------------------------------- #


def test_h1_system_shutdown_idles_executor_within_200ms(rig: Rig) -> None:
    """H1: в момент ``system.shutdown`` у исполнителя активная операция (стоп slow); от ОТПРАВКИ до простоя
    исполнителя ≤ 0,2 с."""
    stop = rig.start_slow_stop()
    _assert_in_transition(rig, "slow", "H1")

    shutdown = rig.send("system.shutdown")
    assert rig.wait_until(rig.system_stop_event.is_set, 15.0) is not None, "system_stop_event не взведён"
    executor = rig.pm._lifecycle_executor
    executor.request_stop()  # как корень PM; идемпотентно
    idle_after = None
    while time.monotonic() - shutdown.t_send < 15.0:
        if executor.join_until(time.monotonic()):
            idle_after = time.monotonic() - shutdown.t_send
            break
        time.sleep(0.005)

    assert idle_after is not None, "исполнитель не вышел в простой за 15 с после system.shutdown"
    assert idle_after <= SHUTDOWN_IDLE_S, f"простой исполнителя через {idle_after:.2f} с, ожидалось ≤ {SHUTDOWN_IDLE_S}"
    reply = rig.wait_reply(stop)
    assert reply is not None and reply.success is False, "прерванный стоп должен ответить success=False"


# --------------------------------------------------------------------------- #
# H2: ни один стоп из описи не ждёт на message_processor
# --------------------------------------------------------------------------- #


def test_h2_no_lifecycle_stop_waits_on_message_processor(rig: Rig) -> None:
    """H2: ожидание смерти ребёнка (``stop_wait_idle``) идёт только на потоке исполнителя ``pm-lifecycle``,
    для всех команд класса L, которые стопают детей."""
    registry = rig.pm._process_registry
    original = registry.stop_wait_idle
    seen: list[str] = []

    def spy(pause_s: float) -> None:
        seen.append(threading.current_thread().name)
        original(pause_s)

    registry.stop_wait_idle = spy

    _remove_slow_topology(rig)
    for command, data in (
        ("process.stop", {"process_name": "slow"}),
        ("process.restart", {"process_name": "other"}),
        ("topology.apply", {"topology_dict": {"processes": {}}}),
    ):
        sent = rig.send(command, data)
        reply = rig.wait_reply(sent)
        assert reply is not None, f"{command}: ответа нет за дедлайн"

    assert seen, "ожидание смерти ребёнка ни разу не вызвало stop_wait_idle — тест ничего не проверил"
    foreign = sorted({name for name in seen if "keyed-pm-lifecycle" not in name})
    assert not foreign, f"ожидание стопа шло не на потоке исполнителя: {foreign}"


# --------------------------------------------------------------------------- #
# H3: _routing_lock свободен, пока исполнитель ждёт ребёнка
# --------------------------------------------------------------------------- #


def test_h3_routing_lock_free_while_executor_waits_for_child(rig: Rig) -> None:
    """H3: пока идёт стоп slow, ``_routing_lock`` берётся с таймаутом 0,1 с с другого потока."""
    rig.start_slow_stop()
    _assert_in_transition(rig, "slow", "H3")
    box: dict[str, bool] = {}

    def grab() -> None:
        lock = rig.pm._routing_lock
        got = lock.acquire(timeout=0.1)
        box["got"] = got
        if got:
            lock.release()

    th = threading.Thread(target=grab, daemon=True, name="h3-grab")
    th.start()
    th.join(5.0)
    assert not th.is_alive(), "захват _routing_lock завис"
    assert box.get("got") is True, "_routing_lock занят, пока исполнитель ждёт смерти ребёнка"


# --------------------------------------------------------------------------- #
# H4: исключение в обработчике L
# --------------------------------------------------------------------------- #


def test_h4_handler_exception_replies_failure_and_queue_goes_on(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """H4: исключение в обработчике L -> ответ с неуспехом, следующая операция исполняется,
    ``_in_transition(<цель>)`` после ответа — ``False``."""
    original = rig.pm.start_process
    calls: list[str | None] = []

    def flaky(process_name: str | None = None) -> bool:
        calls.append(process_name)
        if len(calls) == 1:
            raise RuntimeError("h4-boom")
        return original(process_name)

    monkeypatch.setattr(rig.pm, "start_process", flaky)

    first = Direct(rig, "process.start", {"process_name": "other"})
    assert first.wait(), "ответа на упавшую операцию нет"
    failed = isinstance(first.result, dict) and (
        first.result.get("success") is False or first.result.get("status") == "error"
    )
    assert failed, f"упавшая операция ответила не неуспехом: {first.result}"

    second = Direct(rig, "process.start", {"process_name": "other"})
    assert second.wait(), "следующая операция после упавшей не исполнилась"
    assert second.result == {"success": True, "process_name": "other"}, f"вторая операция: {second.result}"

    cleared = rig.wait_until(lambda: not rig.pm._in_transition("other"), 5.0)
    assert cleared is not None, "_in_transition('other') остался True после ответов"


# --------------------------------------------------------------------------- #
# H6: дымовой тест — вложенная подача в исполнителе
# --------------------------------------------------------------------------- #


def test_h6_nested_topology_apply_inside_executor_runs_in_place(rig: Rig) -> None:
    """H6 (дымовой, не страж): операция класса L внутри исполнителя зовёт ``topology.apply`` через
    ``command_manager`` — исполняется на месте как часть родителя, без дедлока (дедлайн 10 с)."""
    rig.pm._topology_manager.configure(
        diff_fn=lambda current, desired: {"has_changes": True},
        commands_fn=lambda diff, desired: [],
    )
    inner: dict[str, Any] = {}

    def activate(data: Any = None, **kwargs: Any) -> dict:
        done = threading.Event()
        box: dict[str, Any] = {}

        def reply(result: Any) -> None:
            box["result"] = result
            done.set()

        rig.pm.command_manager.handle_command(
            {"command": "topology.apply", "data": {"topology_dict": {"processes": {}}}}, reply=reply
        )
        inner["replied_in_place"] = done.is_set()  # вложенная подача отвечает до возврата handle_command
        inner["thread"] = threading.current_thread().name
        return {"success": True, "nested": box.get("result") is not None}

    registered = rig.pm.command_manager.register_command(
        "test.activate", activate, executor="pm-lifecycle-submit", targets="all"
    )
    assert registered, "тестовая команда не зарегистрирована"

    call = Direct(rig, "test.activate", {})
    assert call.wait(10.0), "вложенная подача в исполнителе не завершилась за 10 с (дедлок)"
    assert call.result == {"success": True, "nested": True}, f"результат: {call.result}"
    assert inner["replied_in_place"] is True, "вложенная операция не исполнилась на месте"
    assert "keyed-pm-lifecycle" in inner["thread"], f"операция шла не на потоке исполнителя: {inner['thread']}"


# --------------------------------------------------------------------------- #
# H7: читатели класса R против писателя на исполнителе
# --------------------------------------------------------------------------- #


def test_h7_readers_survive_dict_mutation_during_topology_apply(rig: Rig) -> None:
    """H7: ``topology.apply`` на исполнителе (стоп slow 3,0 с) + писатель, меняющий ``_active_wires``, +
    200 вызовов ``wire.status`` / ``supervision.status`` / ``topology.get`` с другого потока: 0 исключений
    ``dictionary changed size during iteration``, каждый ответ ≤ 0,5 с. ``_active_wires`` заранее набит
    20 000 записями (иначе итерация без снимка, инъекция И12, не различима)."""
    _remove_slow_topology(rig)
    apply_sent = rig.send("topology.apply", {"topology_dict": {"processes": {}}})
    time.sleep(MID_STOP_S)
    _assert_in_transition(rig, "slow", "H7")

    stop_writer = threading.Event()
    wires = rig.pm._active_wires
    # Итерация по ~400 ключам длится микросекунды — писатель не успевает вклиниться, и итерация по живому словарю
    # (без снимка, инъекция И12) проходила незамеченной (0 из 5). На 20 000 ключей итерация длится десятки
    # миллисекунд: без снимка ~3,5 % вызовов ``wire.status`` падают (замер ревью р.1: 7 из 200), со снимком 0 из 200.
    wires.update(
        {
            f"h7-fill-{i}": {"status": "idle", "source_process": "a", "target_process": "b", "transport": "shm"}
            for i in range(H7_FILL_WIRES)
        }
    )

    def writer() -> None:
        i = 0
        while not stop_writer.is_set():
            key = f"h7-{i % 400}"
            wires[key] = {"status": "idle", "source_process": "a", "target_process": "b", "transport": "shm"}
            if i % 3 == 0:
                wires.pop(f"h7-{(i + 200) % 400}", None)
            i += 1

    errors: list[str] = []
    slowest = [0.0]

    def reader() -> None:
        for i in range(200):
            command = ("wire.status", "supervision.status", "topology.get")[i % 3]
            t0 = time.monotonic()
            result = rig.pm.command_manager.handle_command({"command": command, "data": {}})
            slowest[0] = max(slowest[0], time.monotonic() - t0)
            ok = isinstance(result, dict) and result.get("success") is True
            if not ok:
                errors.append(f"{command}: {result}")

    w = threading.Thread(target=writer, daemon=True, name="h7-writer")
    r = threading.Thread(target=reader, daemon=True, name="h7-reader")
    w.start()
    r.start()
    r.join(60.0)
    stop_writer.set()
    w.join(5.0)
    assert not r.is_alive(), "читатели не уложились в 60 с"
    assert not errors, f"читатели упали ({len(errors)}): {errors[:3]}"
    assert slowest[0] <= FAST_S, f"самый медленный ответ читателя {slowest[0]:.2f} с, ожидалось ≤ {FAST_S}"
    applied = rig.wait_reply(apply_sent)
    assert applied is not None and applied.success is True, "topology.apply не завершился успехом"


# --------------------------------------------------------------------------- #
# H8: один владелец стопа при системном стопе посреди операции
# --------------------------------------------------------------------------- #


def test_h8_single_child_stop_object_until_operation_returns(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """H8: системный стоп посреди стопа slow в исполнителе; корень закрывается (``pm.stop()`` на отдельном
    потоке, как раннер). Число созданных ``ChildProcessStop`` со slow — 1, пока ``stop_process`` не вернулся."""
    created: list[tuple[float, bool]] = []
    original_init = ChildProcessStop.__init__

    def counting_init(self: Any, processes: Any, *args: Any, **kwargs: Any) -> None:
        created.append((time.monotonic(), "slow" in processes))
        original_init(self, processes, *args, **kwargs)

    monkeypatch.setattr(registry_module.ChildProcessStop, "__init__", counting_init)

    returned_at: list[float] = []
    original_stop = rig.pm.stop_process

    def timed_stop(process_name: str | None = None, *args: Any, **kwargs: Any) -> bool:
        try:
            return original_stop(process_name, *args, **kwargs)
        finally:
            returned_at.append(time.monotonic())

    monkeypatch.setattr(rig.pm, "stop_process", timed_stop)

    stop = rig.start_slow_stop()
    _assert_in_transition(rig, "slow", "H8")
    assert sum(1 for _t, has_slow in created if has_slow) == 1, "предусловие H8: объект стопа slow не один"

    rig.send("system.shutdown")
    assert rig.wait_until(rig.system_stop_event.is_set, 15.0) is not None, "system_stop_event не взведён"
    closer = threading.Thread(target=rig.pm.stop, daemon=True, name="h8-pm-stop")
    closer.start()
    closer.join(30.0)
    assert not closer.is_alive(), "pm.stop() (фаза 1 корня) не вернулся за 30 с"

    reply = rig.wait_reply(stop)
    assert reply is not None, "ответ process.stop не пришёл"
    assert returned_at, "stop_process не вернулся"
    before_return = [t for t, has_slow in created if has_slow and t < returned_at[0]]
    assert len(before_return) == 1, (
        f"до возврата операции создано {len(before_return)} объектов стопа со slow, ожидался 1 (два владельца)"
    )


# --------------------------------------------------------------------------- #
# H9: системный стоп без операции — группа корня сама ведёт детей
# --------------------------------------------------------------------------- #


def _close_like_runner(rig: Rig) -> dict:
    """Системный стоп без операции: событие, ``pm.stop()`` на отдельном потоке, затем ``close_root()``."""
    rig.system_stop_event.set()
    th = threading.Thread(target=rig.pm.stop, daemon=True, name="h9-pm-stop")
    th.start()
    th.join(30.0)
    assert not th.is_alive(), "pm.stop() не вернулся за 30 с"
    box: dict[str, Any] = {}

    def close() -> None:
        box["report"] = rig.pm.close_root()

    closer = threading.Thread(target=close, daemon=True, name="h9-close-root")
    closer.start()
    closer.join(60.0)
    assert not closer.is_alive(), "close_root() не вернулся за 60 с"
    return box


def test_h9_system_stop_without_operation_group_stops_children(rig: Rig) -> None:
    """H9: системный стоп без операции в исполнителе (``stop_abort`` поставлен): группа корня не получает
    ``should_abort`` — дети выходят сами с exitcode 0, ``result()`` = все True, 0 строк «ВЫЖИЛИ»."""
    assert rig.pm._process_registry.stop_abort is not None, "предусловие H9: stop_abort не поставлен"
    other = rig.pm._process_registry.get_process_by_name("other")
    _close_like_runner(rig)

    assert rig.slow0.exitcode == 0, f"slow: exitcode {rig.slow0.exitcode}, ожидалось 0 (стоп 3,0 с без terminate)"
    assert other.exitcode == 0, f"other: exitcode {other.exitcode}, ожидалось 0"
    assert rig.pm._children_stop.result() == {"slow": True, "other": True}, rig.pm._children_stop.result()
    lines = [message for _level, message in list(rig.log)]
    assert not [line for line in lines if "ВЫЖИЛИ" in line], "в логе PM есть «ВЫЖИЛИ»"
    assert not [line for line in lines if "terminating" in line], "дети получили terminate при штатном стопе"


def test_h9_hung_child_still_gets_terminate_as_today(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H9 (зависший): ребёнок, чей хук остановки не возвращается, получает ``terminating`` — как сегодня
    (стадия 0 р.3 п.A): группа корня обязана дойти до эскалации, а не прерваться сразу."""
    monkeypatch.setattr(acceptance, "STOP_DELAY_S", 120.0)
    hung = Rig(tmp_path)
    try:
        hung.start()
        _close_like_runner(hung)
        lines = [message for _level, message in list(hung.log)]
        assert any("terminating" in line for line in lines), (
            "зависший slow не получил terminate; хвост лога: " + " | ".join(line[:120] for line in lines[-8:])
        )
    finally:
        hung.close()


# --------------------------------------------------------------------------- #
# H10 (ревью р.1 п.1): системный стоп посреди topology.apply не даёт ложного «unstoppable»
# --------------------------------------------------------------------------- #

UNCONFIRMED_MARK = "НЕ подтверждена"
HANDED_MARK = "handed to the root"


def _record_unstoppable_alerts(rig: Rig) -> list[list[str]]:
    """Подмена ``_publish_unstoppable_alert`` на запись вызовов (оригинал вызывается дальше)."""
    alerts: list[list[str]] = []
    original = rig.pm._publish_unstoppable_alert

    def record(names: list[str]) -> None:
        alerts.append(list(names))
        original(names)

    rig.pm._publish_unstoppable_alert = record
    return alerts


def test_h10_topology_apply_under_system_stop_hands_children_to_root(rig: Rig) -> None:
    """H10 (а): ``topology.apply`` убирает slow (стоп 3,0 с), на +1,0 с приходит ``system.shutdown``:
    0 строк «НЕ подтверждена» (любой уровень), 0 публикаций alert «unstoppable», ровно одна строка WARNING
    «handed to the root» (сид ``_topology_stop_all``); откат (``rollback``) тоже не пишет ERROR."""
    alerts = _record_unstoppable_alerts(rig)
    _remove_slow_topology(rig)
    apply_sent = rig.send("topology.apply", {"topology_dict": {"processes": {}}})
    time.sleep(MID_STOP_S)
    _assert_in_transition(rig, "slow", "H10")
    rig.send("system.shutdown")

    reply = rig.wait_reply(apply_sent)
    assert reply is not None, "topology.apply не ответил за дедлайн после system.shutdown"
    log = list(rig.log)
    lines = [message for _level, message in log]
    unconfirmed = [line for line in lines if UNCONFIRMED_MARK in line]
    assert not unconfirmed, f"системный стоп дал строки «{UNCONFIRMED_MARK}»: {unconfirmed}; ответ: {reply.result}"
    assert alerts == [], f"системный стоп опубликовал alert «unstoppable»: {alerts}; ответ: {reply.result}"
    handed = [(level, line) for level, line in log if HANDED_MARK in line]
    assert len(handed) == 1, f"ожидалась ровно 1 строка «{HANDED_MARK}», есть {len(handed)}: {handed}"
    assert handed[0][0] == "warning", f"строка «{HANDED_MARK}» уровня {handed[0][0]}, ожидался warning"


def test_h10_guard_hung_child_removed_without_system_stop_keeps_error_and_alert(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H10 (страж, б): без системного стопа остановка slow в ``topology.apply`` не подтверждена (``stop_many``
    для slow подменён на ``False`` — настоящий зависший ребёнок на Windows умирает от ``kill`` и подтверждается):
    ERROR «НЕ подтверждена» и alert ``['slow']`` — как сегодня."""
    alerts = _record_unstoppable_alerts(rig)
    registry = rig.pm._process_registry
    real_stop_many = registry.stop_many

    def stop_many_slow_hangs(names: list[str], timeout: float) -> dict[str, bool]:
        others = [n for n in names if n != "slow"]
        result = real_stop_many(others, timeout) if others else {}
        if "slow" in names:
            result["slow"] = False
        return result

    monkeypatch.setattr(registry, "stop_many", stop_many_slow_hangs)
    _remove_slow_topology(rig)
    apply_sent = rig.send("topology.apply", {"topology_dict": {"processes": {}}})

    reply = rig.wait_reply(apply_sent, 90.0)
    assert reply is not None, "topology.apply не ответил за дедлайн"
    errors = [message for level, message in list(rig.log) if level == "error" and UNCONFIRMED_MARK in message]
    assert errors, "без системного стопа нет ERROR «НЕ подтверждена» — регресс страха за зависшего"
    assert alerts and alerts[0] == ["slow"], f"alert «unstoppable» не опубликован или не ['slow']: {alerts}"
    handed = [line for _level, line in list(rig.log) if HANDED_MARK in line]
    assert not handed, f"«{HANDED_MARK}» без системного стопа: {handed}"
