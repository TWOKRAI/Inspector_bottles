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
import time

import pytest

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
    pm._note_point_request(msg(["worker_1"]), "s1", {"success": False, "error": "No handler for key"})
    pm._note_point_request(msg(["worker_1", "worker_2"]), "s1", {"success": True})
    pm._note_point_request({**msg(["worker_1"]), "command": "state.subscribe"}, "s1", {"success": True})
    assert broker.snapshot()["points"] == []

    pm._note_point_request(msg(["worker_1"]), "s1", {"success": True, "result": {"success": True}})
    assert [(p["target"], p["subscriber"]) for p in broker.snapshot()["points"]] == [("worker_1", "gui.s1")]


@pytest.mark.parametrize(
    "answer",
    [
        {"success": False, "error": "timeout"},
        # Отказ БЕЗ тайм-аута обязателен отдельным случаем: тайм-аут у подписки
        # проходит той же веткой, что успех, и один тайм-аутный случай не отличал
        # «снятие учитывается при любом ответе» от «снятие гейтится ответом»
        # (инъекция I9 ведущего 2026-09-23 давала 0 красных).
        {"success": False, "reason": "форвардера нет"},
    ],
)
def test_refused_unsubscribe_still_drops_the_intent(answer):
    """Снятие с отказом/тайм-аутом ребёнка всё равно снимает намерение — иначе оно воскреснет."""
    broker = ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=lambda t, c, d: True)
    pm = _bare_pm(broker)
    sub = {"command": "log.tail.subscribe", "targets": ["worker_1"], "data": {"subscriber": "gui.s1"}}
    unsub = {**sub, "command": "log.tail.unsubscribe"}

    pm._note_point_request(sub, "s1", {"success": True})
    assert len(broker.snapshot()["points"]) == 1
    pm._note_point_request(unsub, "s1", answer)

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


# ---------------------------------------------------------------------------
# Ревью 4.4, итерация 1
# ---------------------------------------------------------------------------


def _plain_broker(send_to=lambda t, c, d: True) -> ObservabilitySubscriptionBroker:
    return ObservabilitySubscriptionBroker(broadcast=lambda c, d: 0, send_to=send_to)


def test_refused_log_untail_without_address_keeps_foreign_intents():
    """log.tail.unsubscribe {} процесс отклоняет («subscriber или tap обязателен») — чужие намерения живы."""
    broker = _plain_broker()
    broker.note_point("pult", "log.tail.subscribe", {"subscriber": "backend_ctl.F"})

    assert broker.note_point("pult", "log.tail.unsubscribe", {}) is False

    assert [p["subscriber"] for p in broker.snapshot()["points"]] == ["backend_ctl.F"]


def test_log_untail_by_tap_removes_exactly_one():
    """Снятие по ``tap`` (log_tail::<адрес>) снимает ровно этот адрес."""
    broker = _plain_broker()
    broker.note_point("pult", "log.tail.subscribe", {"subscriber": "backend_ctl.A"})
    broker.note_point("pult", "log.tail.subscribe", {"subscriber": "backend_ctl.B"})

    assert broker.note_point("pult", "log.tail.unsubscribe", {"tap": "log_tail::backend_ctl.A"}) is True

    assert [p["subscriber"] for p in broker.snapshot()["points"]] == ["backend_ctl.B"]


def test_observability_untail_without_address_still_clears_all_at_target():
    """observability.tail без адреса процесс снимает ВСЕХ (teardown) — реестр зеркалит это."""
    broker = _plain_broker()
    broker.note_point("pult", "observability.tail.subscribe", {"subscriber": "backend_ctl.A"})
    broker.note_point("pult", "observability.tail.subscribe", {"subscriber": "backend_ctl.B"})
    broker.note_point("cam", "observability.tail.subscribe", {"subscriber": "backend_ctl.A"})

    assert broker.note_point("pult", "observability.tail.unsubscribe", {}) is True

    assert [(p["target"], p["subscriber"]) for p in broker.snapshot()["points"]] == [("cam", "backend_ctl.A")]


def test_timeout_subscribe_is_recorded_other_failures_are_not():
    """Тайм-аут подписки записывается (ребёнок мог подписаться), прочий явный отказ — нет."""
    broker = _plain_broker()
    pm = _bare_pm(broker)
    sub = {"command": "log.tail.subscribe", "targets": ["worker_1"], "data": {"subscriber": "gui.s1"}}

    pm._note_point_request(sub, "s1", {"success": False, "error": "No handler for key"})
    assert broker.snapshot()["points"] == []

    pm._note_point_request(sub, "s1", {"success": False, "error": "timeout", "correlation_id": "c1"})
    assert [p["subscriber"] for p in broker.snapshot()["points"]] == ["gui.s1"]


def test_unsubscribe_landing_mid_replay_does_not_resurrect():
    """Гонка (a): снятие s2 приходит, пока replay отправляет s1, — s2 не доигрывается."""
    sent: list = []

    def send_to(target, command, data):
        sent.append(data.get("subscriber"))
        if len(sent) == 1:
            ok, errors = _run_with_deadline(
                lambda: broker.note_point("worker_1", "log.tail.unsubscribe", {"subscriber": "backend_ctl.s2"})
            )
            assert ok and errors == []
        return True

    broker = _plain_broker(send_to)
    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "backend_ctl.s1"})
    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "backend_ctl.s2"})

    result = broker.replay(target="worker_1")

    assert sent == ["backend_ctl.s1"]
    assert [r["subscriber"] for r in result["points"]["replayed"]] == ["backend_ctl.s1"]


def test_subscribe_answer_after_session_closed_is_not_recorded():
    """Гонка (b): сокет закрыт (forget_session) раньше, чем read-поток дописал успешную подписку."""
    broker = _plain_broker()
    pm = _bare_pm(broker)

    pm._forget_closed_session("s9")
    pm._note_point_request(
        {"command": "log.tail.subscribe", "targets": ["pult"], "data": {"subscriber": "backend_ctl.s9"}},
        "s9",
        {"success": True, "result": {"success": True}},
    )

    assert broker.snapshot()["points"] == []


# ---------------------------------------------------------------------------
# Ревью 4.4, итерация 2
# ---------------------------------------------------------------------------


def _pm_without_broker() -> ProcessManagerProcess:
    """PM, у которого брокер ещё НЕ создан (живьём — до первой подписки системы)."""
    pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm._log_error = lambda _m: None
    pm._log_info = lambda _m: None
    pm._send_child_command = lambda t, c, d: True
    pm._broadcast_command = lambda c, d: 0
    return pm


def test_session_closed_before_broker_exists_late_subscribe_not_recorded():
    """Сессия закрылась, когда брокера ещё не было; запоздалый успешный ответ подписки — не сирота."""
    pm = _pm_without_broker()

    pm._forget_closed_session("s9")
    pm._note_point_request(
        {"command": "log.tail.subscribe", "targets": ["pult"], "data": {"subscriber": "backend_ctl.s9"}},
        "s9",
        {"success": True},
    )

    assert pm._observability_broker_obj().snapshot()["points"] == []


def test_log_untail_tap_wins_over_subscriber_like_the_process():
    """{subscriber: F, tap: log_tail::G}: процесс снимает tap G — реестр снимает G, F остаётся."""
    broker = _plain_broker()
    broker.note_point("pult", "log.tail.subscribe", {"subscriber": "backend_ctl.F"})
    broker.note_point("pult", "log.tail.subscribe", {"subscriber": "backend_ctl.G"})

    broker.note_point("pult", "log.tail.unsubscribe", {"subscriber": "backend_ctl.F", "tap": "log_tail::backend_ctl.G"})

    assert [p["subscriber"] for p in broker.snapshot()["points"]] == ["backend_ctl.F"]


def test_log_untail_foreign_tap_form_leaves_registry_untouched():
    """tap чужой формы процесс снимет как есть — сопоставить его адресу нельзя, реестр не трогается."""
    broker = _plain_broker()
    broker.note_point("pult", "log.tail.subscribe", {"subscriber": "backend_ctl.F"})

    assert broker.note_point("pult", "log.tail.unsubscribe", {"subscriber": "backend_ctl.F", "tap": "other"}) is False

    assert [p["subscriber"] for p in broker.snapshot()["points"]] == ["backend_ctl.F"]


def test_concurrent_first_broker_access_builds_one_broker(monkeypatch):
    """Два read-потока впервые зовут фабрику брокера — брокер один (иначе память сессий раздваивается)."""
    orig_init = ObservabilitySubscriptionBroker.__init__

    def slow_init(self, *a, **k):
        time.sleep(0.05)  # расширить окно «проверь-и-создай»
        orig_init(self, *a, **k)

    monkeypatch.setattr(ObservabilitySubscriptionBroker, "__init__", slow_init)
    pm = _pm_without_broker()
    got: list = []
    threads = [
        threading.Thread(target=lambda: got.append(pm._observability_broker_obj()), daemon=True) for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_DEADLINE_S)

    assert not any(t.is_alive() for t in threads)
    assert len({id(b) for b in got}) == 1
    assert pm._observability_broker is got[0]
