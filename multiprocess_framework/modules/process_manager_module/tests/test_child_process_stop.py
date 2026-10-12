"""Авторские hazard-тесты Task 1.1: ``ChildProcessStop`` в области и в реестре.

Что может сломаться в этом механизме: контракт ``Stoppable`` (иначе область примет объект
за вызываемое), тексты лога для живых тестов, имя без ``stop_event``, гонка ``request_stop``
из другого потока, окна эскалации через ``Scope`` и одна связка с настоящими процессами.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

from ...base_manager import open_scope
from ...base_manager.interfaces import Stoppable
from ..core.child_process_stop import ChildProcessStop
from ..core.process_registry import ProcessRegistry


class _Proc:
    def __init__(self, *, dies_on: str | None = None, alive_raises: bool = False) -> None:
        self._alive = True
        self._dies_on = dies_on
        self._alive_raises = alive_raises
        self.terminate_t: list[float] = []
        self.kill_t: list[float] = []

    def is_alive(self) -> bool:
        if self._alive_raises:
            raise OSError("poll boom")
        return self._alive

    def terminate(self) -> None:
        self.terminate_t.append(time.monotonic())
        if self._dies_on == "terminate":
            self._alive = False

    def kill(self) -> None:
        self.kill_t.append(time.monotonic())
        if self._dies_on == "kill":
            self._alive = False


class _Event:
    def __init__(self) -> None:
        self.calls = 0

    def set(self) -> None:
        self.calls += 1


class _RecLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _log_info(self, msg: str) -> None:
        self.lines.append(msg)

    def _log_warning(self, msg: str) -> None:
        self.lines.append(msg)

    def _log_error(self, msg: str) -> None:
        self.lines.append(msg)


def _bounded(fn: Any, limit_s: float = 10.0) -> Any:
    box: dict[str, Any] = {}
    th = threading.Thread(target=lambda: box.setdefault("r", fn()), daemon=True)
    th.start()
    th.join(limit_s)
    assert not th.is_alive(), f"вызов завис дольше {limit_s} с"
    return box.get("r")


def test_is_stoppable_so_scope_gives_it_phase_two() -> None:
    """Сторожит: имена ``request_stop``/``join_until``: без них ``own`` счёл бы объект вызываемым
    или отверг бы, и фаза 2 к сроку не наступила бы."""
    assert isinstance(ChildProcessStop({}, {}), Stoppable)


def test_log_texts_caught_by_live_tests() -> None:
    """Сторожит: подстроки ``did not stop in`` и ``Force killing`` — их ловят живые тесты
    ``backend_ctl/tests/test_graceful_stop_live.py`` и ``test_system_shutdown_live.py``."""
    logger = _RecLogger()
    p = _Proc(dies_on="kill")
    cs = ChildProcessStop({"W": p}, {"W": _Event()}, logger=logger, terminate_grace_s=0.05, poll_s=0.01)
    cs.request_stop()
    cs.kill()
    assert _bounded(lambda: cs.join_until(time.monotonic() + 1.0)) is True
    assert any("Process 'W' did not stop in" in line and "terminating..." in line for line in logger.lines)
    assert any("Force killing process 'W'" in line for line in logger.lines)


def test_missing_stop_event_logged_and_escalation_still_kills() -> None:
    """Сторожит: ветку ``event is None`` в ``request_stop`` — лог один раз, без исключения;
    процесс без события останавливается эскалацией."""
    logger = _RecLogger()
    p = _Proc(dies_on="terminate")
    cs = ChildProcessStop({"N": p}, {}, logger=logger, poll_s=0.01)
    cs.request_stop()
    cs.request_stop()
    assert sum("нет stop_event" in line for line in logger.lines) == 1
    assert cs.join_until(time.monotonic() + 0.1) is False
    cs.kill()
    assert cs.join_until(time.monotonic() + 1.0) is True


def test_is_alive_failure_is_not_a_confirmed_death() -> None:
    """Сторожит: ``_alive`` — сбой ``is_alive()`` не метит процесс мёртвым (метка на живом
    читателе портит его поток)."""
    marks: list[str] = []
    cs = ChildProcessStop({"X": _Proc(alive_raises=True)}, {}, on_confirmed_dead=lambda n, _p: marks.append(n))
    assert cs.join_until(time.monotonic() - 1.0) is False
    assert cs.survivors() == ("X",)
    cs.close()
    assert marks == []


def test_request_stop_from_other_thread_during_join_marks_once() -> None:
    """Сторожит: лок вокруг ``_dead`` — ``request_stop``/``survivors`` из другого потока во время
    ``join_until`` не дают второй метки и не роняют ожидание."""
    marks: list[str] = []
    t0 = time.monotonic()

    class _DiesAt(_Proc):
        def is_alive(self) -> bool:
            return time.monotonic() < t0 + 0.2

    cs = ChildProcessStop(
        {"A": _DiesAt(), "B": _DiesAt()},
        {"A": _Event(), "B": _Event()},
        on_confirmed_dead=lambda n, _p: marks.append(n),
        poll_s=0.001,
    )
    stop = threading.Event()

    def hammer() -> None:
        while not stop.is_set():
            cs.request_stop()
            cs.survivors()

    th = threading.Thread(target=hammer, daemon=True)
    th.start()
    try:
        assert _bounded(lambda: cs.join_until(t0 + 2.0)) is True
    finally:
        stop.set()
        th.join(2.0)
    assert sorted(marks) == ["A", "B"]


def test_scope_windows_graceful_then_terminate_then_kill() -> None:
    """Сторожит: область ``pm/stop`` (budget, ``KILL_RESERVE_S``) держит прежние окна:
    terminate — по сроку graceful, настоящий kill — через ``terminate_grace_s`` после него."""
    p = _Proc(dies_on="kill")
    cs = ChildProcessStop({"S": p}, {"S": _Event()}, terminate_grace_s=0.3, kill_confirm_s=0.3, poll_s=0.01)
    scope = open_scope("test/stop", budget_s=0.2, kill_reserve_s=0.6)
    t0 = time.monotonic()
    try:
        scope.own(cs, name="children", kind="process")
    finally:
        report = _bounded(scope.close)
    assert report.survivors == ()
    assert report.killed == ("test/stop/children",)
    assert len(p.terminate_t) == 1 and len(p.kill_t) == 1
    assert 0.2 - 0.1 <= p.terminate_t[0] - t0 <= 0.2 + 0.2
    assert 0.3 - 0.1 <= p.kill_t[0] - p.terminate_t[0] <= 0.3 + 0.2


def _sleep_forever() -> None:
    time.sleep(60)


def test_registry_stop_many_with_real_processes() -> None:
    """Связка с настоящими объектами: ``Process`` + ``Event`` + область через ``stop_many``.
    Спящий не слушает stop_event — убит по эскалации; результат True, срок ≈ graceful + окно."""
    ctx = multiprocessing.get_context("spawn")
    registry = ProcessRegistry(logger=None)
    procs = []
    for name in ("P1", "P2"):
        registry._stop_events[name] = ctx.Event()
        proc = ctx.Process(target=_sleep_forever, name=name, daemon=True)
        registry.add_process(proc)
        procs.append(proc)
    try:
        for proc in procs:
            proc.start()
        t0 = time.monotonic()
        result = _bounded(lambda: registry.stop_many(["P1", "P2"], timeout=0.3), 20.0)
        elapsed = time.monotonic() - t0
        assert result == {"P1": True, "P2": True}
        assert all(not proc.is_alive() for proc in procs)
        assert registry._stop_events["P1"].is_set() and registry._stop_events["P2"].is_set()
        assert elapsed < 0.3 + 1.0 + 1.0 + 0.5
    finally:
        for proc in procs:
            if proc.is_alive():
                proc.kill()
            proc.join(3.0)
