# -*- coding: utf-8 -*-
"""Task 1.2 (gui-graceful-close) — авторские тесты опасностей: итог стопа на пути корня (ADR-PMM-042).

H1 — два настоящих писателя итога (``_stop_many`` на своём потоке и группа корня) и правило ранга;
H2 — итог корня не сбрасывается снятием процесса и отказанным рестартом посреди стопа;
H3 — ``survived`` пишется только после ``kill()`` и срока, до этого ``None``;
H4 — F1: группа корня не собралась (реестр бросил), после ``kill()`` фаза ``done`` объявлена ровно один раз;
страж — подтверждение смерти (метка читателя) не ставится с потока, который читает статус.

Дети — фейковые (``FakeChild`` из ``test_pm_responsive_during_children_stop.py``), без spawn. Всё, что может
повиснуть, идёт в daemon-потоке с дедлайном join. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from ..core.child_process_stop import ChildProcessStop
from ..core.process_registry import ProcessRegistry
from ..process.process_manager_process import _ChildrenStop
from .test_pm_responsive_during_children_stop import FakeChild, Rig

JOIN_DEADLINE_S = 15.0
ROOT_CLOSED_DEADLINE_S = 40.0
STOP_MANY_THREAD = "h1-stop-many"


def _registry(*children: FakeChild, system_stop: threading.Event | None = None) -> ProcessRegistry:
    """Настоящий реестр без очередей: дети и их ``stop_event`` — как у ``create_and_register``."""
    registry = ProcessRegistry(system_stop_event=system_stop)
    for child in children:
        registry.add_process(child)
        registry._stop_events[child.name] = child.stop_event
    return registry


def _start(target: Any, name: str) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = target()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name=name)
    thread.start()
    return thread, box


def _finish(thread: threading.Thread, box: dict[str, Any]) -> Any:
    thread.join(JOIN_DEADLINE_S)
    assert not thread.is_alive(), f"{thread.name}: не вернулся за {JOIN_DEADLINE_S} с"
    assert "error" not in box, repr(box.get("error"))
    return box.get("result")


def _root_stop(registry: ProcessRegistry, *, phase2_s: float = 0.3, phase3_s: float = 2.0) -> bool:
    """Фазы области ``children`` корня по порядку: сигнал, ожидание, ``kill()``, ожидание фазы 3."""
    group = registry.children_stop(mark_reader_gone=True)
    group.request_stop()
    if group.join_until(time.monotonic() + phase2_s):
        return True
    group.kill()
    return group.join_until(time.monotonic() + phase3_s)


# --------------------------------------------------------------------------- #
# H1: ранг — два настоящих писателя на разных потоках
# --------------------------------------------------------------------------- #


def _late_stop_many_writer(child: FakeChild) -> str | None:
    """Корень подтверждает смерть ``child`` первым, ``_stop_many`` того же имени пишет ПОСЛЕ него.

    Поток ``_stop_many`` держится в своей паузе опроса (``stop_wait_idle``), пока корень не закончит;
    затем его группа видит смерть, которой сама не вызывала, и считает ``exited``.
    """
    registry = _registry(child)
    root_done = threading.Event()

    def idle(pause: float) -> None:
        if threading.current_thread().name == STOP_MANY_THREAD:
            root_done.wait(JOIN_DEADLINE_S)
        else:
            time.sleep(pause)

    registry.stop_wait_idle = idle
    writer, writer_box = _start(lambda: registry.stop_many([child.name], 5.0), STOP_MANY_THREAD)
    deadline = time.monotonic() + 5.0
    while child.stop_signals < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert child.stop_signals >= 1, "предусловие: стоп по одному не послал сигнал"

    def root() -> bool:
        try:
            # Срок фазы 3 = KILL_CONFIRM_S + 0,2 с: настоящий kill уходит почти сразу.
            return _root_stop(registry, phase2_s=0.0, phase3_s=1.2)
        finally:
            root_done.set()

    root_thread, root_box = _start(root, "h1-root")
    assert _finish(root_thread, root_box) is True, "корень не подтвердил смерть"
    assert _finish(writer, writer_box) == {child.name: True}
    return registry.stop_outcome(child.name)


def _late_handed_over(child: FakeChild) -> str | None:
    """``_stop_many`` прерван системным стопом и снял снимок ``handed_over``; запись — после ``terminated`` корня."""
    registry = _registry(child)
    registry.stop_abort = lambda: True
    root_done = threading.Event()
    snapshot_taken = threading.Event()
    real_outcomes = ChildProcessStop.outcomes

    def outcomes(self: ChildProcessStop) -> dict[str, str]:
        result = real_outcomes(self)
        if threading.current_thread().name == STOP_MANY_THREAD:
            snapshot_taken.set()
            root_done.wait(JOIN_DEADLINE_S)
        return result

    with patch.object(ChildProcessStop, "outcomes", outcomes):
        writer, writer_box = _start(lambda: registry.stop_many([child.name], 5.0), STOP_MANY_THREAD)
        assert snapshot_taken.wait(JOIN_DEADLINE_S), "стоп по одному не дошёл до итога"

        def root() -> bool:
            try:
                return _root_stop(registry, phase2_s=0.0, phase3_s=1.2)
            finally:
                root_done.set()

        root_thread, root_box = _start(root, "h1-root")
        assert _finish(root_thread, root_box) is True, "корень не подтвердил смерть"
        assert _finish(writer, writer_box) == {child.name: False}
    return registry.stop_outcome(child.name)


@pytest.mark.timeout(60)
def test_outcome_rank_two_writers() -> None:
    """``exited`` и ``handed_over`` от ``_stop_many`` не затирают ``terminated`` корня; ``killed`` побеждает."""
    terminated = FakeChild("cam", [], mode="terminate")
    assert _late_stop_many_writer(terminated) == "terminated"

    handed = FakeChild("cam", [], mode="terminate")
    assert _late_handed_over(handed) == "terminated"

    hard = FakeChild("hard", [], mode="kill")  # переживает terminate, умирает на kill
    assert _late_stop_many_writer(hard) == "killed"


# --------------------------------------------------------------------------- #
# H2: итог корня не сбрасывается снятием процесса и отказанным рестартом
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_outcome_not_reset_by_monitor_pause_or_refused_restart_during_stop() -> None:
    """Корень записал ``exited``/``terminated``; затем ``remove_process`` (путь рестарта) и отказ спавна на
    системном стопе (``create_and_register`` -> ``None``) — итог прежний."""
    system_stop = threading.Event()
    polite = FakeChild("polite", [], mode="slow", exit_after_s=0.05)
    cam = FakeChild("cam", [], mode="terminate")
    registry = _registry(polite, cam, system_stop=system_stop)
    system_stop.set()

    thread, box = _start(lambda: _root_stop(registry, phase2_s=0.5, phase3_s=2.0), "h2-root")
    assert _finish(thread, box) is True
    # Предусловие: без него тест зелёный до правки (итога нет — и сбрасывать нечего).
    assert registry.stop_outcome("polite") == "exited"
    assert registry.stop_outcome("cam") == "terminated"

    for name in ("polite", "cam"):
        registry.remove_process(name)
        assert registry.create_and_register(name, "fake.Child", {}) is None, "спавн на системном стопе не отвергнут"

    assert registry.stop_outcome("polite") == "exited"
    assert registry.stop_outcome("cam") == "terminated"


# --------------------------------------------------------------------------- #
# H3: survived — только после kill() и срока
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_survived_only_after_kill_and_deadline() -> None:
    """Ребёнок переживает и terminate, и kill: после фазы 2 итог ``None``, после фазы 3 — ``survived``;
    умер позже — подтверждённый итог (ранг выше) затирает ``survived``."""
    stuck = FakeChild("stuck", [], mode="terminate")
    stuck.terminate = lambda: None  # type: ignore[method-assign]
    stuck.kill = lambda: None  # type: ignore[method-assign]
    registry = _registry(stuck)
    group = registry.children_stop(mark_reader_gone=True)

    def phase2() -> bool:
        group.request_stop()
        return group.join_until(time.monotonic() + 0.3)

    thread, box = _start(phase2, "h3-phase2")
    assert _finish(thread, box) is False
    assert registry.stop_outcome("stuck") is None, "survived до kill() — ложь о живом ребёнке"

    def phase3() -> bool:
        group.kill()
        return group.join_until(time.monotonic() + 0.3)

    thread, box = _start(phase3, "h3-phase3")
    assert _finish(thread, box) is False
    assert registry.stop_outcome("stuck") == "survived"

    stuck._die(-9)
    thread, box = _start(group.close, "h3-close")
    _finish(thread, box)
    assert registry.stop_outcome("stuck") == "killed"


# --------------------------------------------------------------------------- #
# H4: F1 — группы нет (реестр бросил), после kill() фаза done ровно один раз
# --------------------------------------------------------------------------- #


@pytest.fixture
def make_rig():
    rigs: list[Rig] = []

    def factory(graceful_s: float) -> Rig:
        rig = Rig(graceful_s)
        rigs.append(rig)
        rig.start()
        return rig

    try:
        yield factory
    finally:
        for rig in rigs:
            rig.close()


@pytest.mark.timeout(120)
def test_f1_done_announced_when_group_none_and_killed(make_rig) -> None:
    """``registry.children_stop`` бросает (``_start_failed``): на ``kill()`` фаза ещё ``children``; к закрытию корня
    фаза ``done`` и запись стора ``done`` — ровно одна."""
    rig = make_rig(1.0)
    pm = rig.pm
    store = pm._state_store_manager
    real_set = store.handle_state_set
    phases: list[Any] = []

    def spy(message: Any, *args: Any, **kwargs: Any) -> Any:
        data = message.get("data") if isinstance(message, dict) and isinstance(message.get("data"), dict) else message
        if isinstance(data, dict) and str(data.get("path", "")) == "system.stop.phase":
            phases.append(data.get("value"))
        return real_set(message, *args, **kwargs)

    store.handle_state_set = spy

    def broken_children_stop(*, mark_reader_gone: bool) -> Any:
        raise RuntimeError("реестр упал (H4)")

    pm._process_registry.children_stop = broken_children_stop
    phase_at_kill: list[Any] = []
    start_failed_at_kill: list[bool] = []
    real_kill = _ChildrenStop.kill

    def kill(self: _ChildrenStop) -> None:
        phase_at_kill.append((self._pm._system_stop_snapshot() or {}).get("phase"))
        start_failed_at_kill.append(self._start_failed)
        real_kill(self)

    with patch.object(_ChildrenStop, "kill", kill):
        pm.stop_event.set()
        assert rig.wait_root_closed(ROOT_CLOSED_DEADLINE_S), "корень PM не закрылся за дедлайн"

    assert start_failed_at_kill == [True], f"предусловие: группа должна не собраться: {start_failed_at_kill}"
    assert phase_at_kill == ["children"], phase_at_kill
    assert (pm._system_stop_snapshot() or {}).get("phase") == "done", pm._system_stop_snapshot()
    assert phases.count("done") == 1, phases
    assert phases[0] == "children", phases


# --------------------------------------------------------------------------- #
# H5: листовой лок записи итога — проверка ранга и запись атомарны
# --------------------------------------------------------------------------- #


class _GatedOutcomes(dict):
    """Словарь итогов, чьё первое чтение на потоке ``A`` снимает значение и ЗАТЕМ ждёт (≤ 0,5 с) записи ``B``:
    окно «прочитал — записал» писателя расширено детерминированно."""

    def __init__(self, a_thread: str, a_reading: threading.Event, b_wrote: threading.Event) -> None:
        super().__init__()
        self._a_thread = a_thread
        self._a_reading = a_reading
        self._b_wrote = b_wrote
        self._gated = False

    def get(self, key: Any, default: Any = None) -> Any:
        value = super().get(key, default)
        if not self._gated and threading.current_thread().name == self._a_thread:
            self._gated = True
            self._a_reading.set()
            # С локом B ждёт лок, и это ожидание истекает по таймауту (не взаимоблокировка).
            self._b_wrote.wait(0.5)
        return value


@pytest.mark.timeout(30)
def test_outcome_lock_makes_rank_check_and_write_atomic() -> None:
    """A прочитал «итога нет» и пишет ``handed_over``; B между чтением и записью A пишет ``terminated``.
    С листовым локом B ждёт A и пишет вторым — итог ``terminated``; без лока A затирает его ``handed_over``."""
    registry = ProcessRegistry()
    a_reading, b_wrote = threading.Event(), threading.Event()
    registry._stop_outcomes = _GatedOutcomes("h5-A", a_reading, b_wrote)

    writer_a, box_a = _start(lambda: registry._record_stop_outcome("cam", "handed_over"), "h5-A")
    assert a_reading.wait(3.0), "поток A не дошёл до чтения итога"

    def writer_b() -> None:
        try:
            registry._record_stop_outcome("cam", "terminated")
        finally:
            b_wrote.set()

    thread_b, box_b = _start(writer_b, "h5-B")
    for thread, box in ((writer_a, box_a), (thread_b, box_b)):
        thread.join(3.0)
        assert not thread.is_alive(), f"{thread.name}: не вернулся за 3 с"
        assert "error" not in box, repr(box.get("error"))

    assert registry.stop_outcome("cam") == "terminated"


# --------------------------------------------------------------------------- #
# Страж: читатель статуса не подтверждает смерть
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_message_processor_thread_does_not_confirm_death(make_rig) -> None:
    """Пока корень стопит детей, ``supervision.status`` опрашивается часто. Метка «читатель ушёл» (эффект
    подтверждения смерти) ставится только на потоке, который ведёт ожидание группы, и ровно один раз на имя."""
    rig = make_rig(5.0)
    quick = rig.add_child("quick", mode="slow", exit_after_s=0.3)
    stubborn = rig.add_child("stubborn", mode="terminate")
    registry = rig.pm._process_registry
    assert rig.wait_until(
        lambda: (
            {"quick", "stubborn"}
            <= set((rig.wait_reply(rig.send("supervision.status")).result or {}).get("processes", {}))
        ),
        10.0,
    ), "дети не попали в supervision.status"

    marks: list[tuple[str, int]] = []
    readers: set[int] = set()
    waiters: set[int] = set()
    real_mark = registry._mark_confirmed_dead
    real_outcome = registry.stop_outcome
    real_join = ChildProcessStop.join_until

    def mark(name: str, process: Any) -> Any:
        marks.append((name, threading.get_ident()))
        return real_mark(name, process)

    def outcome(name: str) -> Any:
        readers.add(threading.get_ident())
        return real_outcome(name)

    def join_until(self: ChildProcessStop, deadline: float) -> bool:
        waiters.add(threading.get_ident())
        return real_join(self, deadline)

    registry._mark_confirmed_dead = mark
    registry.stop_outcome = outcome
    with patch.object(ChildProcessStop, "join_until", join_until):
        rig.send("system.shutdown")
        end = time.monotonic() + 15.0
        while time.monotonic() < end and not (quick.dead.is_set() and time.monotonic() - (quick.t_dead or 0) > 0.3):
            rig.wait_reply(rig.send("supervision.status"), 2.0)
        assert quick.dead.is_set(), "быстрый ребёнок не вышел"
        assert stubborn.is_alive(), "предусловие: упрямый уже мёртв — окно стопа не воспроизведено"

    assert readers, "статус не читал итог посреди стопа"
    quick_marks = [ident for name, ident in marks if name == "quick"]
    assert len(quick_marks) == 1, f"метка quick не ровно одна: {marks}"
    assert set(quick_marks) <= waiters, (
        f"метку поставил не поток ожидания группы: метка {quick_marks}, ожидание {waiters}, читатели {readers}"
    )
