# -*- coding: utf-8 -*-
"""Тесты ObservabilityTailActivator (Ф5.20b) — активация и переподписка live-хвоста.

Закрытие долга: авто-рестарт поднимает новую инкарнацию с тем же именем → дедуп по
имени блокировал переподписку → после рестарта хвост процесса пропадал. Триггер
переподписки — supervisor.event=recovered.
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.observability import ObservabilityTailActivator


class RecordingSend:
    """Мок send_command: копит (target, command, args)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, target, command, args):
        self.calls.append((target, command, args))


def _delta(path, value=None):
    return {"data_type": "state_delta", "path": path, "value": value}


def test_subscribes_process_on_first_sight():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")
    act.on_state_delta(_delta("processes.cam.state.fps", 30))
    assert send.calls == [("cam", "observability.tail.subscribe", {"subscriber": "gui"})]


def test_dedup_one_subscription_per_process():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")
    act.on_state_delta(_delta("processes.cam.state.fps", 30))
    act.on_state_delta(_delta("processes.cam.state.fps", 31))
    act.on_state_delta(_delta("processes.cam.workers.w1.status", "running"))
    assert len(send.calls) == 1  # cam подписан ровно раз


def test_resubscribe_on_recovered_after_restart():
    """Долг закрыт: supervisor.event=recovered → переподписать новую инкарнацию."""
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")
    act.on_state_delta(_delta("processes.cam.state.fps", 30))  # первичная подписка
    assert len(send.calls) == 1
    # Рестарт → recovered → снять дедуп и переподписать
    act.on_state_delta(_delta("processes.cam.supervisor.event", "recovered"))
    assert len(send.calls) == 2
    assert send.calls[1] == ("cam", "observability.tail.subscribe", {"subscriber": "gui"})


def test_no_resubscribe_on_other_supervisor_events():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")
    act.on_state_delta(_delta("processes.cam.state.fps", 30))
    act.on_state_delta(_delta("processes.cam.supervisor.event", "restarting"))
    act.on_state_delta(_delta("processes.cam.supervisor.event", "crashed"))
    assert len(send.calls) == 1  # только recovered переподписывает


def test_does_not_subscribe_self():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")
    act.on_state_delta(_delta("processes.gui.state.fps", 60))
    assert send.calls == []


def test_ignores_non_process_and_non_delta():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")
    act.on_state_delta(_delta("system.chain_fps", 30))
    act.on_state_delta({"data_type": "gui_local_metric", "path": "processes.cam.x", "value": 1})
    act.on_state_delta({"data_type": "observability_record", "records": []})
    assert send.calls == []


def test_send_exception_swallowed():
    def boom(*a, **k):
        raise RuntimeError("router down")

    act = ObservabilityTailActivator(boom, "gui")
    act.on_state_delta(_delta("processes.cam.state.fps", 30))  # не должно бросить


def test_multiple_processes_each_subscribed():
    send = RecordingSend()
    act = ObservabilityTailActivator(send, "gui")
    for p in ("cam", "preprocessor", "stitcher"):
        act.on_state_delta(_delta(f"processes.{p}.state.fps", 1))
    assert {c[0] for c in send.calls} == {"cam", "preprocessor", "stitcher"}
