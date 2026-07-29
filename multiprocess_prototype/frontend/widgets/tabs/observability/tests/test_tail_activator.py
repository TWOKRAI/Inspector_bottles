# -*- coding: utf-8 -*-
"""Тесты ObservabilityTailActivator (Task 5.11) — намерение объявляется ОДИН раз.

Прежняя редакция проверяла цикл подписки по процессам и переподписку по
``supervisor.event="recovered"``. Этой логики больше нет: её забрал брокер на
оркестраторе — вместе с резидуалом F4, из-за которого ручной рестарт и hot-swap
оставляли новую инкарнацию без хвоста (``recovered`` они не публикуют).

Что проверяется теперь: один выстрел, правильный адресат, и что GUI больше НЕ
разбирает состав системы.
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.observability import ObservabilityTailActivator

SUBSCRIBE_ALL = "observability.tail.subscribe_all"


class RecordingSend:
    """Мок send_command: копит (target, command, args)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, target, command, args):
        self.calls.append((target, command, args))


def _delta(path, value=None):
    return {"data_type": "state_delta", "path": path, "value": value}


def test_announces_intent_once_to_the_broker():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    act.on_state_delta(_delta("processes.cam.state.fps", 30))

    assert send.calls == [("ProcessManager", SUBSCRIBE_ALL, {"subscriber": "gui"})]


def test_further_deltas_do_not_produce_more_commands():
    """Один выстрел, а не цикл: дельт ``processes.*`` идут сотни в секунду."""
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    for path in (
        "processes.cam.state.fps",
        "processes.preprocessor.state.fps",
        "processes.stitcher.workers.w1.status",
        "processes.cam.supervisor.event",
    ):
        act.on_state_delta(_delta(path, 1))

    assert len(send.calls) == 1


def test_gui_does_not_name_a_single_process():
    """Состав системы — забота брокера; в конверте GUI нет ни одного имени процесса."""
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    act.on_state_delta(_delta("processes.cam.state.fps", 30))

    target, _command, args = send.calls[0]
    assert target == "ProcessManager"
    assert args == {"subscriber": "gui"}


def test_waits_for_the_first_process_delta():
    """Дельта ``processes.*`` — первое доказательство, что оркестратор отвечает;
    команда, посланная раньше, ушла бы в пустоту молча."""
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")

    act.on_state_delta(_delta("system.chain_fps", 30))
    act.on_state_delta({"data_type": "gui_local_metric", "path": "processes.cam.x", "value": 1})
    act.on_state_delta({"data_type": "observability_record", "records": []})

    assert send.calls == []
    assert act.announced is False


def test_transport_failure_does_not_turn_one_shot_into_a_retry_storm():
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("router down")

    act = ObservabilityTailActivator(boom, "gui")

    act.on_state_delta(_delta("processes.cam.state.fps", 30))  # не должно бросить
    act.on_state_delta(_delta("processes.cam.state.fps", 31))
    act.on_state_delta(_delta("processes.det.state.fps", 31))

    assert calls["n"] == 1
    assert act.announced is True
