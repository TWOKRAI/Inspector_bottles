# -*- coding: utf-8 -*-
"""Авторские hazard-тесты view_state/memo в CommandDispatcherOrchestrator (Task 1.1).

Проверяют внутренние риски механизма (порядок, реентерабельность, изоляция ошибок),
которые не видны из приёмочных критериев. Независимые приёмочные тесты -- рядом
(pipeline/tests/test_acceptance_undo_selection.py, actions_module/tests/...).

Refs: plans/undo-restores-selection.md (Task 1.1)
"""

from __future__ import annotations

from multiprocess_prototype.adapters.dispatch.command_dispatcher import (
    CommandDispatcherOrchestrator,
    ProjectHolder,
)
from multiprocess_prototype.domain.commands import AddProcess
from multiprocess_prototype.domain.entities.project import ApplyContext, Project
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import ProcessAdded, TopologyReplaced
from multiprocess_prototype.domain.tests._fakes import FakeTopologyRepository


class _PublishingRepo(FakeTopologyRepository):
    """Как настоящий store (G.3): save() синхронно публикует TopologyReplaced."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self._bus = bus

    def save(self, topology: Topology) -> None:
        super().save(topology)
        self._bus.publish(TopologyReplaced(reason="test"))


def _build() -> tuple[CommandDispatcherOrchestrator, EventBus, list[str]]:
    bus = EventBus()
    log: list[str] = []
    bus.subscribe(TopologyReplaced, lambda _e: log.append("topology_replaced"))
    disp = CommandDispatcherOrchestrator(
        project_holder=ProjectHolder(initial=Project(topology=Topology())),
        topology_repo=_PublishingRepo(bus),
        event_bus=bus,
        apply_context_factory=ApplyContext,
    )
    return disp, bus, log


def test_listener_runs_after_topology_replaced_reload() -> None:
    """Слушатель вида зовётся ПОСЛЕ синхронного TopologyReplaced (scene уже перерисована).

    Ломается, если _apply_memo поставить до _restore: выбор восстановился бы на старую
    scene, а reload его затёр.
    """
    disp, _bus, log = _build()
    disp.add_view_restore_listener(lambda _m: log.append("listener"))
    disp.dispatch(AddProcess(process_name="a"), view_state=lambda: "memo")
    log.clear()

    assert disp.undo() is True

    assert log == ["topology_replaced", "listener"]


def test_listener_runs_before_change_callbacks() -> None:
    """Слушатель зовётся до _notify_change; ломается перестановкой шагов в undo()."""
    disp, _bus, log = _build()
    disp.add_view_restore_listener(lambda _m: log.append("listener"))
    disp.add_change_callback(lambda: log.append("change"))
    disp.dispatch(AddProcess(process_name="a"), view_state=lambda: "memo")
    log.clear()

    disp.undo()

    assert log.index("listener") < log.index("change")


def test_raising_listener_does_not_stop_undo_other_listeners_or_notify() -> None:
    """Исключение в слушателе не срывает undo, соседей и change-callback.

    Ломается, если убрать try/except в _apply_memo: undo бросит, _notify_change не вызовется.
    """
    disp, _bus, log = _build()

    def bad(_m: object) -> None:
        raise RuntimeError("boom")

    disp.add_view_restore_listener(bad)
    disp.add_view_restore_listener(lambda _m: log.append("second"))
    disp.add_change_callback(lambda: log.append("change"))
    disp.dispatch(AddProcess(process_name="a"), view_state=lambda: "memo")
    log.clear()

    assert disp.undo() is True

    assert "second" in log and "change" in log


class _HostileCallback:
    """Слушатель, у которого падают И вызов, И __repr__/__str__/__qualname__ (ревью 1.1, N4)."""

    def __repr__(self) -> str:
        raise RuntimeError("repr broken")

    __str__ = __repr__

    def __getattr__(self, name: str) -> object:
        raise RuntimeError("getattr broken")

    def __call__(self, *_args: object) -> None:
        raise RuntimeError("call broken")


def test_hostile_listener_repr_does_not_break_undo_or_neighbours() -> None:
    """Слушатель с падающим __repr__ и вызовом: undo True, соседи и change-callback живы.

    Ломается, если в logger.exception вернуть `%r` от колбэка: форматирование записи
    бросит из except-блока и undo упадёт вместе с остальными слушателями.
    """
    disp, _bus, log = _build()
    disp.add_view_restore_listener(_HostileCallback())
    disp.add_view_restore_listener(lambda _m: log.append("second"))
    disp.add_change_callback(lambda: log.append("change"))
    disp.dispatch(AddProcess(process_name="a"), view_state=lambda: "memo")
    log.clear()

    assert disp.undo() is True

    assert "second" in log and "change" in log


def test_hostile_change_callback_repr_does_not_break_notify() -> None:
    """То же для change-callback: сосед после враждебного колбэка всё равно вызван."""
    disp, _bus, log = _build()
    disp.add_change_callback(_HostileCallback())
    disp.add_change_callback(lambda: log.append("change"))

    events = disp.dispatch(AddProcess(process_name="a"))

    assert [type(e) for e in events] == [ProcessAdded]
    assert "change" in log


def test_raising_view_state_does_not_fail_dispatch_and_gives_no_memo() -> None:
    """view_state бросает: dispatch проходит, запись без memo, undo не зовёт слушателей.

    Ломается, если убрать try/except в _capture_view_state: вид UI начнёт валить мутацию
    модели, а Project останется без записи в истории.
    """
    disp, _bus, log = _build()
    disp.add_view_restore_listener(lambda m: log.append(f"listener:{m}"))

    def boom() -> object:
        raise RuntimeError("view broken")

    events = disp.dispatch(AddProcess(process_name="a"), view_state=boom)

    assert [type(e) for e in events] == [ProcessAdded]
    assert disp.can_undo() is True
    log.clear()
    assert disp.undo() is True
    assert not any(x.startswith("listener") for x in log)


def test_view_state_captured_before_apply_and_after_publish() -> None:
    """memo_before снимается до apply, memo_after -- после публикации событий.

    Ломается, если оба снимка сделать в одной точке: undo/redo вернут один и тот же выбор.
    """
    disp, bus, log = _build()
    bus.subscribe(ProcessAdded, lambda _e: log.append("process_added"))
    calls = iter(["before", "after"])

    def view() -> object:
        value = next(calls)
        log.append(f"view:{value}")
        return value

    seen: list[object] = []
    disp.add_view_restore_listener(seen.append)
    disp.dispatch(AddProcess(process_name="a"), view_state=view)

    assert log.index("view:before") < log.index("process_added") < log.index("view:after")
    disp.undo()
    disp.redo()
    assert seen == ["before", "after"]


def test_removed_listener_is_not_called() -> None:
    """После remove_view_restore_listener слушатель молчит (утечка presenter после dispose)."""
    disp, _bus, log = _build()

    def cb(_m: object) -> None:
        log.append("listener")

    disp.add_view_restore_listener(cb)
    disp.remove_view_restore_listener(cb)
    disp.remove_view_restore_listener(cb)  # повторное удаление безопасно
    disp.dispatch(AddProcess(process_name="a"), view_state=lambda: "memo")

    disp.undo()

    assert "listener" not in log
