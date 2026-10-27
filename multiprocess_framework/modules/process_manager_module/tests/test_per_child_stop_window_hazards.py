# -*- coding: utf-8 -*-
"""Task 1.11 — hazard-тесты автора (H1–H5): эскалация по окну имени в ``ChildProcessStop`` и реестре.

Фейк-процессы (на Windows настоящий ``terminate`` убивает сразу — «игнорирует terminate» без фейка не
показать). Время — ``time.monotonic()``; ожидаемые моменты — литералы из окон теста. Каждый вызов, который
может зависнуть, идёт в daemon-потоке с дедлайном join.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ..core.child_process_stop import ChildProcessStop
from ..core.process_registry import ProcessRegistry
from ..core.stop_budget import stop_budget

_JOIN_S = 15.0


class _Event:
    """Событие стопа с моментом ``set()``."""

    def __init__(self) -> None:
        self.at: float | None = None

    def set(self) -> None:
        if self.at is None:
            self.at = time.monotonic()


class _FakeProc:
    """Процесс: выходит сам через ``exit_after`` после события (None — никогда), terminate можно игнорировать."""

    def __init__(self, name: str, event: _Event, *, exit_after: float | None = None, ignore_terminate: bool = False):
        self.name = name
        self.pid = 0
        self._event = event
        self._exit_after = exit_after
        self._ignore_terminate = ignore_terminate
        self.dead_at: float | None = None
        self.terminate_at: list[float] = []
        self.kill_at: list[float] = []

    def is_alive(self) -> bool:
        if self.dead_at is not None:
            return False
        at = self._event.at
        if self._exit_after is not None and at is not None and time.monotonic() >= at + self._exit_after:
            self.dead_at = at + self._exit_after
            return False
        return True

    def terminate(self) -> None:
        self.terminate_at.append(time.monotonic())
        if not self._ignore_terminate and self.dead_at is None:
            self.dead_at = time.monotonic()

    def kill(self) -> None:
        self.kill_at.append(time.monotonic())
        if self.dead_at is None:
            self.dead_at = time.monotonic()


def _bounded(fn: Callable[[], Any]) -> Any:
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пересылается в тест
            box["error"] = exc

    th = threading.Thread(target=_run, daemon=True, name="hazard-call")
    th.start()
    th.join(_JOIN_S)
    assert not th.is_alive(), f"вызов не вернулся за {_JOIN_S} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _registry(procs: list[_FakeProc], events: dict[str, _Event], windows: dict[str, Any]) -> ProcessRegistry:
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0), max_stop_window_s=12.0)
    for proc in procs:
        registry.os_processes.append(proc)
        registry._stop_events[proc.name] = events[proc.name]
    for name, window in windows.items():
        registry._register_stop_window(name, {"stop_window_s": window})
    return registry


# --------------------------------------------------------------------------- #
# H1: abort внутри окна имени — ни одного сигнала по имени, handed_over
# --------------------------------------------------------------------------- #


def test_h1_abort_inside_name_window_sends_nothing() -> None:
    """Окно 0,2; abort с 0,1; опрос 1,0 — следующий проход ровно на сроке имени.

    Правильный порядок (abort раньше сроков имён) — ни terminate, ни kill; обратный — terminate на 0,2.
    """
    ev = _Event()
    proc = _FakeProc("a", ev)
    t0 = time.monotonic()
    stop = ChildProcessStop(
        {"a": proc},
        {"a": ev},
        poll_s=1.0,
        should_abort=lambda: time.monotonic() - t0 >= 0.1,
        windows_s={"a": 0.2},
    )
    stop.request_stop()
    ok = _bounded(lambda: stop.join_until(time.monotonic() + 3.0))
    stop.kill()
    assert ok is False and stop.aborted is True
    assert proc.terminate_at == [] and proc.kill_at == [], (proc.terminate_at, proc.kill_at)
    assert stop.outcomes() == {"a": "handed_over"}


# --------------------------------------------------------------------------- #
# H2: имя игнорирует terminate — kill в w_i + 1,0, не в сроке области + 1
# --------------------------------------------------------------------------- #


def test_h2_name_ignoring_terminate_killed_at_window_plus_grace() -> None:
    ev = _Event()
    proc = _FakeProc("a", ev, ignore_terminate=True)
    stop = ChildProcessStop({"a": proc}, {"a": ev}, windows_s={"a": 0.3})
    stop.request_stop()
    t0 = ev.at
    assert t0 is not None
    ok = _bounded(lambda: stop.join_until(time.monotonic() + 5.0))
    assert ok is True
    assert len(proc.terminate_at) == 1 and 0.25 <= proc.terminate_at[0] - t0 <= 0.5, proc.terminate_at
    assert len(proc.kill_at) == 1 and 1.25 <= proc.kill_at[0] - t0 <= 1.6, proc.kill_at
    assert stop.outcomes() == {"a": "killed"}


# --------------------------------------------------------------------------- #
# H2b + H3: w_i ∈ (D − 1, D) — kill имени в фазе 3 по его сроку; kill() области не шлёт второй terminate
# --------------------------------------------------------------------------- #


def test_h2b_h3_window_near_deadline_kill_in_phase3_single_terminate() -> None:
    """Область ``pm/stop`` срок D = 1,0; окно 0,5: terminate 0,5, kill 1,5 (фаза 3), не D − 1 = 0,0 и не 2,0."""
    ev = _Event()
    proc = _FakeProc("a", ev, ignore_terminate=True)
    registry = _registry([proc], {"a": ev}, {"a": 0.5})
    t_call = time.monotonic()
    result = _bounded(lambda: registry.stop_many(["a"], 1.0, mark_reader_gone=False))
    t0 = ev.at
    assert t0 is not None and t0 - t_call < 0.2
    assert result == {"a": True}
    assert len(proc.terminate_at) == 1, f"H3: terminate {len(proc.terminate_at)} раз: {proc.terminate_at}"
    assert 0.45 <= proc.terminate_at[0] - t0 <= 0.75, proc.terminate_at
    assert len(proc.kill_at) == 1 and 1.45 <= proc.kill_at[0] - t0 <= 1.8, proc.kill_at
    assert registry.stop_outcome("a") == "killed"


# --------------------------------------------------------------------------- #
# H4: пакетный путь реестра (rollback / topology — один вызов stop_many) берёт окно имени
# --------------------------------------------------------------------------- #


def test_h4_batch_path_window_per_name() -> None:
    """``stop_many`` 0,3 с: A (окно 0,8, выход сам на 0,6) — exited; B без ключа (игнорирует стоп) — terminate ~0,3."""
    events = {"A": _Event(), "B": _Event()}
    a = _FakeProc("A", events["A"], exit_after=0.6)
    b = _FakeProc("B", events["B"])
    registry = _registry([a, b], events, {"A": 0.8})
    result = _bounded(lambda: registry.stop_many(["A", "B"], 0.3, mark_reader_gone=False))
    t0 = events["A"].at
    assert t0 is not None
    assert result == {"A": True, "B": True}
    assert a.terminate_at == [] and a.kill_at == []
    assert len(b.terminate_at) == 1 and 0.25 <= b.terminate_at[0] - t0 <= 0.5, b.terminate_at
    assert (registry.stop_outcome("A"), registry.stop_outcome("B")) == ("exited", "terminated")


def test_h4_no_key_in_group_keeps_old_path() -> None:
    """Ни у одного имени нет ключа — группа без ``windows_s`` (прежний путь байт в байт)."""
    events = {"B": _Event()}
    b = _FakeProc("B", events["B"])
    registry = _registry([b], events, {})
    _, stop = registry._build_child_stop(["B"], False, default_window_s=0.3)
    assert stop is not None and stop.windows_s is None


# --------------------------------------------------------------------------- #
# H5: stop_process(None) → stop_all — окна по именам
# --------------------------------------------------------------------------- #


def test_h5_stop_all_uses_name_windows() -> None:
    events = {"A": _Event(), "B": _Event()}
    a = _FakeProc("A", events["A"], exit_after=0.6)
    b = _FakeProc("B", events["B"])
    registry = _registry([a, b], events, {"A": 0.8})
    result = _bounded(lambda: registry.stop_all(timeout=0.3, mark_reader_gone=False))
    t0 = events["A"].at
    assert t0 is not None
    assert result == {"A": True, "B": True}
    assert a.terminate_at == [], a.terminate_at
    assert len(b.terminate_at) == 1 and 0.25 <= b.terminate_at[0] - t0 <= 0.5, b.terminate_at


# --------------------------------------------------------------------------- #
# H7: явный stop(timeout=X) выше потолка — внешний срок от X (max(X, G)), не от G
# --------------------------------------------------------------------------- #


class _FakeOrchestrator:
    """Живой двойник PM для ``ProcessSpawner.stop``: пишет срок внешнего ``join``; после ``join`` мёртв."""

    def __init__(self) -> None:
        self.alive = True
        self.join_timeouts: list[float | None] = []

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        self.alive = False

    def terminate(self) -> None:
        self.alive = False

    def kill(self) -> None:
        self.alive = False


def test_spawner_explicit_timeout_above_ceiling_wins() -> None:
    """Потолок 10, ``shutdown_timeout`` 5, ``stop(timeout=12.0)`` → внешний join 15,5 (12 + 1 + 1 + 1,5), не 13,5."""
    from ..launcher.spawner import ProcessSpawner

    spawner = ProcessSpawner(stop_timeout=5.0, orchestrator_config={"shutdown_timeout": 5.0, "max_stop_window_s": 10.0})
    fake = _FakeOrchestrator()
    spawner._process = fake
    _bounded(lambda: spawner.stop(timeout=12.0))
    assert fake.join_timeouts, "spawner.stop() не позвал join"
    assert abs(fake.join_timeouts[0] - 15.5) < 1e-9, fake.join_timeouts
