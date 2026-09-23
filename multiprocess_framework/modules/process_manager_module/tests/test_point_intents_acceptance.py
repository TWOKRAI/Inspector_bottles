# -*- coding: utf-8 -*-
"""Независимая приёмка контракта точечных намерений брокера (Задача 4.4, RED).

Написано ДО реализации по дизайну лида (карточка "Task 4.4" в
plans/observability-closure/phase-4-scale-and-form.md). Брокеру ещё не
существует ни ``note_point``, ни точечной части ``replay``/``forget_session``/
``snapshot``, ни модульных констант ``POINT_COMMANDS``/``REASON_LOOP`` —
поэтому весь файл обязан быть RED на коммите 575f336d.

Слепота: видел только публичный API/конструктор ``observability_broker.py``
(существующий оптовый механизм ``subscribe_all``/``_fan_out``/``forget_session``),
не видел реализацию точечных намерений и авторские тесты
``test_observability_broker.py``.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_manager_module.process import (
    observability_broker as ob,
)
from multiprocess_framework.modules.process_manager_module.process.observability_broker import (
    ObservabilitySubscriptionBroker,
)


def _make_broker(send_to):
    """Брокер с фейковым send_to и broadcast, который точечная раздача не должна звать."""

    def _broadcast_must_not_be_called(command, data):
        raise AssertionError(f"точечное намерение не должно уходить broadcast'ом (command={command!r}, data={data!r})")

    return ObservabilitySubscriptionBroker(broadcast=_broadcast_must_not_be_called, send_to=send_to)


def test_replay_sends_point_intent_to_restarted_target_only():
    """replay(target=X) шлёт СТОРОННЕЕ намерение X адресно, X-намерение чужого target не трогает."""
    sent = []

    def send_to(target, command, data):
        sent.append((target, command, dict(data)))
        return True

    broker = _make_broker(send_to)

    ok1 = broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "gui.session1", "level": "INFO"})
    ok2 = broker.note_point("worker_2", "log.tail.subscribe", {"subscriber": "gui.session2"})
    assert ok1 is True
    assert ok2 is True

    result = broker.replay(target="worker_1", reason="instance.started")

    # СТОРОННИЙ payload (без добавленного "scope") ушёл ровно на worker_1.
    assert sent == [("worker_1", "log.tail.subscribe", {"subscriber": "gui.session1", "level": "INFO"})]

    points = result["points"]
    assert len(points["replayed"]) == 1
    replayed = points["replayed"][0]
    assert replayed["target"] == "worker_1"
    assert replayed["command"] == "log.tail.subscribe"
    assert replayed["subscriber"] == "gui.session1"
    assert points["skipped"] == []
    assert points["failed"] == []


def test_unsubscribe_removes_intent_and_replay_sends_nothing():
    """Парный unsubscribe снимает намерение — последующий replay(target=X) не шлёт ничего."""
    sent = []

    def send_to(target, command, data):
        sent.append((target, command, dict(data)))
        return True

    broker = _make_broker(send_to)

    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "gui.session1"})
    removed = broker.note_point("worker_1", "log.tail.unsubscribe", {"subscriber": "gui.session1"})
    assert removed is True

    result = broker.replay(target="worker_1")

    assert sent == []
    assert result["points"]["replayed"] == []


def test_loop_intent_skipped_with_literal_reason_and_not_counted_as_failure_neighbour_delivered():
    """subscriber == target — петля: skipped с буквальным REASON_LOOP, не failed; сосед доставлен."""
    sent = []

    def send_to(target, command, data):
        sent.append((target, command, dict(data)))
        return True

    broker = _make_broker(send_to)

    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "worker_1"})
    broker.note_point("worker_1", "observability.tail.subscribe", {"subscriber": "neighbour"})

    result = broker.replay(target="worker_1")

    literal_reason = "подписка процесса на собственный хвост — петля (записи ушли бы в свою же очередь)"
    assert ob.REASON_LOOP == literal_reason

    points = result["points"]
    assert [it["subscriber"] for it in points["skipped"]] == ["worker_1"]
    assert points["skipped"][0]["reason"] == literal_reason
    assert points["skipped"][0]["reason"] == ob.REASON_LOOP

    assert [it["subscriber"] for it in points["replayed"]] == ["neighbour"]
    assert sent == [("worker_1", "observability.tail.subscribe", {"subscriber": "neighbour"})]

    # Петля — не сбой раздачи, счётчик failed трогать не должна.
    assert broker.snapshot()["point_replay_failed"] == 0


def test_failed_send_counted_and_replay_does_not_raise():
    """send_to упавший исключением ИЛИ вернувший False — в failed, счётчик растёт, replay не падает."""

    def send_to(target, command, data):
        if command == "log.tail.subscribe":
            raise RuntimeError("транспорт упал")
        return False

    broker = _make_broker(send_to)

    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "a"})
    broker.note_point("worker_1", "observability.tail.subscribe", {"subscriber": "b"})

    result = broker.replay(target="worker_1")  # не должен бросить исключение наружу

    points = result["points"]
    assert sorted(it["subscriber"] for it in points["failed"]) == ["a", "b"]
    assert points["replayed"] == []
    assert broker.snapshot()["point_replay_failed"] == 2


def test_forget_session_drops_only_that_session_points_and_sends_unsubscribe():
    """forget_session(sid) снимает точечные намерения ТОЛЬКО этой сессии и шлёт unsubscribe."""
    sent = []

    def send_to(target, command, data):
        sent.append((target, command, dict(data)))
        return True

    broker = _make_broker(send_to)

    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "gui.sess1"})
    broker.note_point("worker_1", "observability.tail.subscribe", {"subscriber": "gui.sess2"})

    broker.forget_session("sess1")

    assert ("worker_1", "log.tail.unsubscribe", {"subscriber": "gui.sess1"}) in sent
    assert not any(call[2].get("subscriber") == "gui.sess2" for call in sent)

    sent.clear()
    result = broker.replay(target="worker_1")
    assert [it["subscriber"] for it in result["points"]["replayed"]] == ["gui.sess2"]


def test_ui_tap_unsubscribe_with_empty_payload_clears_target():
    """ui.tap.unsubscribe с пустым payload снимает ВСЕ ui.tap-намерения этого target."""
    sent = []

    def send_to(target, command, data):
        sent.append((target, command, dict(data)))
        return True

    broker = _make_broker(send_to)

    broker.note_point("worker_1", "ui.tap.subscribe", {"subscriber": "gui.sess1"})
    broker.note_point("worker_1", "ui.tap.subscribe", {"subscriber": "gui.sess2"})

    cleared = broker.note_point("worker_1", "ui.tap.unsubscribe", {})
    assert cleared is True

    result = broker.replay(target="worker_1")
    assert result["points"]["replayed"] == []
    assert sent == []


def test_non_point_command_ignored_returns_false():
    """Команда вне POINT_COMMANDS — note_point возвращает False, реестр не меняется."""
    broker = _make_broker(send_to=lambda target, command, data: True)

    result = broker.note_point("worker_1", "some.other.command", {"subscriber": "x"})

    assert result is False
    assert broker.snapshot()["points"] == []


def test_has_intents_true_with_only_point_intent():
    """has_intents() учитывает точечный реестр, даже когда оптовый пуст."""
    broker = _make_broker(send_to=lambda target, command, data: True)

    assert broker.has_intents() is False

    broker.note_point("worker_1", "log.tail.subscribe", {"subscriber": "gui.sess1"})

    assert broker.has_intents() is True
