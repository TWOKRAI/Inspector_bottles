# -*- coding: utf-8 -*-
"""Авторские hazard-тесты точечного реестра брокера (Задача 4.4).

Дополнение к независимой приёмке ``test_point_intents_acceptance.py`` — только то,
что видно из устройства механизма:

- реестр пишет read-поток сокета, а читает replay из message_processor/монитора —
  один лок на двоих, гонка обязана не терять намерения;
- ``forget_session`` шлёт снятия из read-потока канала: отправка под локом брокера
  заперла бы любого, кто в этот момент читает брокер из другого потока;
- точечная раздача не имеет права тронуть оптовую (маркер ``scope``);
- наблюдатель PM запоминает только принятую одноадресную подписку, а шов
  инкарнации доигрывает реестр из одних точечных намерений.

Всё, что может заблокироваться, крутится в daemon-потоке с дедлайном join.
"""

from __future__ import annotations

import threading

from multiprocess_framework.modules.process_manager_module.process.observability_broker import (
    ObservabilitySubscriptionBroker,
)
from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)

_DEADLINE_S = 5.0


def _run_with_deadline(fn) -> tuple[bool, list]:
    """Выполнить fn в daemon-потоке; (успел ли, [исключение?])."""
    errors: list = []

    def _body():
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается в тест
            errors.append(exc)

    t = threading.Thread(target=_body, daemon=True)
    t.start()
    t.join(_DEADLINE_S)
    return (not t.is_alive()), errors


def test_note_point_concurrent_with_replay_loses_no_intent():
    """16 писателей note_point (read-поток сокета) параллельно с replay (монитор): ни потерь, ни исключений.

    Smoke, не доказательство лока: под GIL вставка в dict атомарна, и снятие лока
    с ``note_point`` этот тест НЕ уронит. Ловит исключение итерации по меняющемуся
    словарю в replay/snapshot и потерю намерения при составной правке без лока.
    """
    writers, per_writer = 16, 50
    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=lambda t, c, d: True)
    stop = threading.Event()
    errors: list = []
    start = threading.Barrier(writers + 1)

    def writer(i: int) -> None:
        try:
            start.wait(_DEADLINE_S)
            for j in range(per_writer):
                assert broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": f"gui.s{i}_{j}"})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def replayer() -> None:
        try:
            start.wait(_DEADLINE_S)
            while not stop.is_set():
                broker.replay(target="worker_1")
                broker.snapshot()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(writers)]
    rt = threading.Thread(target=replayer, daemon=True)
    for t in [*threads, rt]:
        t.start()
    for t in threads:
        t.join(_DEADLINE_S)
    stop.set()
    rt.join(_DEADLINE_S)

    assert not any(t.is_alive() for t in [*threads, rt]), "поток завис"
    assert errors == []
    assert len(broker.snapshot()["points"]) == writers * per_writer
    assert len(broker.replay(target="worker_1")["points"]["replayed"]) == writers * per_writer


def test_forget_session_sends_outside_the_lock():
    """send_to, ждущий чтения брокера из ДРУГОГО потока, не должен запереться в forget_session.

    RLock пускает повторный вход в том же потоке, поэтому реентерабельность
    проверяется чужим потоком: он берёт ``snapshot()`` и отдаёт результат, пока
    ``forget_session`` ждёт в ``send_to``. Отправка под локом → чужой поток ждёт
    лок, send_to ждёт чужой поток → дедлайн.
    """
    readers_done: list = []

    def send_to(target, command, data):
        t = threading.Thread(target=lambda: readers_done.append(broker.snapshot()), daemon=True)
        t.start()
        t.join(1.0)
        return not t.is_alive()

    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=send_to)
    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "gui.sessX"})
    broker.note_point("worker_2", "ui.tap.subscribe", {"subscriber": "gui.sessX"})

    finished, errors = _run_with_deadline(lambda: broker.forget_session("sessX"))

    assert finished, "forget_session завис: отправка под локом брокера"
    assert errors == []
    # Оба чужих чтения прошли, пока forget_session стоял в send_to.
    assert len(readers_done) == 2
    assert broker.snapshot()["points"] == []


def test_wholesale_replay_keeps_scope_marker_point_replay_has_none():
    """Одна цель, оптовое + точечное намерение: оптовое адресно с scope='all', точечное — дословно."""
    sent: list = []

    def send_to(target, command, data):
        sent.append((target, command, dict(data)))
        return True

    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 1, send_to=send_to)
    broker.subscribe_all("gui.whole", level="INFO")
    broker.note_point("worker_1", "observability.tail.subscribe", {"subscriber": "gui.point", "level": "DEBUG"})
    sent.clear()

    broker.replay(target="worker_1")

    assert (
        "worker_1",
        "observability.tail.subscribe",
        {"subscriber": "gui.whole", "level": "INFO", "scope": "all"},
    ) in sent
    assert ("worker_1", "observability.tail.subscribe", {"subscriber": "gui.point", "level": "DEBUG"}) in sent
    assert len(sent) == 2


def _bare_pm(broker: ObservabilitySubscriptionBroker) -> ProcessManagerProcess:
    """PM без инициализации: только то, что читают наблюдатель и шов инкарнации."""
    pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm._observability_broker = broker
    pm._log_error = lambda _m: None
    return pm


def test_note_point_request_ignores_failed_result_and_multi_target():
    """Наблюдатель PM: отказ ребёнка (на любом уровне конверта) и многоадресное сообщение не запоминаются."""
    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=lambda t, c, d: True)
    pm = _bare_pm(broker)

    def msg(targets):
        return {"command": "log.tail.subscribe", "targets": targets, "data": {"subscriber": "gui.s1"}}

    pm._note_point_request(msg(["worker_1"]), "s1", {"success": True, "result": {"success": False, "reason": "x"}})
    pm._note_point_request(msg(["worker_1"]), "s1", {"success": False, "error": "timeout"})
    pm._note_point_request(msg(["worker_1", "worker_2"]), "s1", {"success": True})
    pm._note_point_request({**msg(["worker_1"]), "command": "state.subscribe"}, "s1", {"success": True})
    assert broker.snapshot()["points"] == []

    pm._note_point_request(msg(["worker_1"]), "s1", {"success": True, "result": {"success": True}})
    assert [(p["target"], p["subscriber"]) for p in broker.snapshot()["points"]] == [("worker_1", "gui.s1")]


def test_refused_unsubscribe_still_drops_the_intent():
    """Снятие с отказом/тайм-аутом ребёнка всё равно снимает намерение — иначе оно воскреснет."""
    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=lambda t, c, d: True)
    pm = _bare_pm(broker)
    sub = {"command": "log.tail.subscribe", "targets": ["worker_1"], "data": {"subscriber": "gui.s1"}}
    unsub = {**sub, "command": "log.tail.unsubscribe"}

    pm._note_point_request(sub, "s1", {"success": True})
    assert len(broker.snapshot()["points"]) == 1
    pm._note_point_request(unsub, "s1", {"success": False, "error": "timeout"})

    assert broker.snapshot()["points"] == []


def test_refused_subscribe_records_nothing():
    """Контроль пары: отказ на ПОДПИСКУ по-прежнему не запоминается."""
    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=lambda t, c, d: True)
    pm = _bare_pm(broker)
    sub = {"command": "log.tail.subscribe", "targets": ["worker_1"], "data": {"subscriber": "gui.s1"}}

    pm._note_point_request(sub, "s1", {"success": True, "result": {"success": False, "reason": "нет hub"}})

    assert broker.snapshot()["points"] == []


def test_point_only_registry_still_replays_on_instance_started():
    """Шов инкарнации: реестр из одних точечных намерений ставит отложенную раздачу (было: ранний return)."""
    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=lambda t, c, d: True)
    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "gui.s1"})
    pm = _bare_pm(broker)
    scheduled: list = []
    pm.get_config = lambda _key: None
    pm._run_when_child_ready = lambda name, action, **kw: scheduled.append(name)

    pm._replay_observability_when_ready("worker_1")

    assert scheduled == ["worker_1"]
