# -*- coding: utf-8 -*-
"""Task 1.1 (system-run-state) — слепые тесты проводки ``run_event``: PM -> ProcessRegistry -> runner -> ребёнок.

Контракт — DESIGN п.3 ``plans/2026-10-27_system-run-state/tasks/1.1.md``
(копия ADR-PMM-034 для ``system_ready_event``):
``ProcessRegistry(run_event=...)`` -> kwargs ``Process`` -> keyword-only
``run_process_function(..., *, run_event=None)`` -> атрибут ``_run_event`` экземпляра ДО ``initialize()``;
``run_event=None`` не затирает уже стоящее значение.

Образцы: ``test_t54_ready_event_wiring.py`` (патч ``ProcessRegistry``, ``PrerollChild`` для настоящего spawn).
Каждый блокирующий вызов — в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import inspect
import multiprocessing
import os
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ..core.process_registry import ProcessRegistry
from ..runner.process_runner import run_process_function
from .conftest import make_pm

_PM_MOD = "multiprocess_framework.modules.process_manager_module.process.process_manager_process"
_RUNNER_MOD = "multiprocess_framework.modules.process_manager_module.runner.process_runner"
_THIS = "multiprocess_framework.modules.process_manager_module.tests.test_run_event_wiring"
_SPAWN_DEADLINE_S = 30.0


# --------------------------------------------------------------------------- #
# PM -> ProcessRegistry
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [True, False])
def test_process_manager_hands_run_event_to_registry(run_gate: bool) -> None:
    """``ProcessRegistry`` получает kwarg ``run_event`` — тот же объект, что ``pm._run_event``."""
    pm = make_pm()
    pm.update_config("run_gate", run_gate)
    with (
        patch(f"{_PM_MOD}.ProcessRegistry") as reg_cls,
        patch(f"{_PM_MOD}.ProcessPriority"),
        patch(f"{_PM_MOD}.ProcessStatusMonitor"),
        patch(f"{_PM_MOD}.ProcessMonitor"),
        patch(f"{_PM_MOD}.QueueRegistry"),
    ):
        pm._create_components()

    assert pm._run_event is not None, "событие не создано до ProcessRegistry(...)"
    assert reg_cls.call_args.kwargs.get("run_event") is pm._run_event, reg_cls.call_args
    assert pm._run_event.is_set() is (not run_gate), "при run_gate true событие снято, при false — взведено сразу"
    # событие работы — отдельное от события готовности системы
    assert reg_cls.call_args.kwargs.get("run_event") is not reg_cls.call_args.kwargs.get("system_ready_event")


# --------------------------------------------------------------------------- #
# Настоящий spawn: событие видно ребёнку в обе стороны
# --------------------------------------------------------------------------- #


class EdgeChild:
    """Процесс-ребёнок: наблюдает ``self._run_event`` (атрибут ставит runner) и пишет в ``marks.txt`` фронты.

    Метки: ``has_event=True|False``; ``CLEAR_SEEN`` (увидел снятое), ``SET_SEEN`` (после снятого увидел взведённое),
    ``CLEARED_AGAIN`` (после взведённого снова увидел снятое).
    """

    def __init__(self, name: str, shared_resources, config) -> None:
        self.name = name
        self._dir = Path(os.environ["RUN_EVT_DIR"])
        self._own_ready = None
        self._stop = threading.Event()

    def _mark(self, text: str) -> None:
        with open(self._dir / "marks.txt", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    def initialize(self) -> bool:
        return True

    def attach_ready_event(self, event) -> None:
        self._own_ready = event

    def run(self) -> None:
        ev = getattr(self, "_run_event", None)
        self._mark(f"has_event={ev is not None}")
        if ev is not None:
            threading.Thread(target=self._watch, args=(ev,), daemon=True, name="run-evt-watch").start()
        if self._own_ready is not None:
            self._own_ready.set()

    def _watch(self, ev) -> None:
        phase = "want_clear"
        while not self._stop.is_set():
            is_set = ev.is_set()
            if phase == "want_clear" and not is_set:
                self._mark("CLEAR_SEEN")
                phase = "want_set"
            elif phase == "want_set" and is_set:
                self._mark("SET_SEEN")
                phase = "want_clear_again"
            elif phase == "want_clear_again" and not is_set:
                self._mark("CLEARED_AGAIN")
                return
            time.sleep(0.01)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        self._stop.set()

    def shutdown(self) -> None:
        self._stop.set()


def _marks(workdir: Path) -> list[str]:
    path = workdir / "marks.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _wait(predicate, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _in_daemon(fn, deadline_s: float) -> None:
    """Выполнить ``fn`` в daemon-потоке с дедлайном; исключение потока пробрасывается."""
    box: dict[str, BaseException] = {}

    def go() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    th = threading.Thread(target=go, daemon=True, name="run-evt-scenario")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"сценарий завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]


@pytest.mark.timeout(120)
def test_spawned_child_sees_run_event_both_directions(tmp_path, monkeypatch) -> None:
    """Настоящий spawn: родитель переключает событие уже ПОСЛЕ спавна, ребёнок видит оба фронта."""
    monkeypatch.setenv("RUN_EVT_DIR", str(tmp_path))

    def scenario() -> None:
        run_event = multiprocessing.Event()  # снято на момент спавна
        registry = ProcessRegistry(logger=None, run_event=run_event)
        process = registry.create_and_register("run_evt_child", f"{_THIS}.EdgeChild", {}, "normal")
        assert process is not None, "create_and_register вернул None"
        try:
            process.start()
            own_ready = registry.get_ready_event("run_evt_child")
            assert own_ready is not None
            assert own_ready.wait(_SPAWN_DEADLINE_S), (
                f"ребёнок не объявил готовность за {_SPAWN_DEADLINE_S} с "
                f"(alive={process.is_alive()}, exitcode={process.exitcode}, marks={_marks(tmp_path)})"
            )
            assert "has_event=True" in _marks(tmp_path), _marks(tmp_path)
            assert _wait(lambda: "CLEAR_SEEN" in _marks(tmp_path), 10.0), _marks(tmp_path)
            assert "SET_SEEN" not in _marks(tmp_path)

            run_event.set()  # передний фронт — после спавна
            assert _wait(lambda: "SET_SEEN" in _marks(tmp_path), 10.0), f"ребёнок не увидел set(): {_marks(tmp_path)}"
            run_event.clear()  # задний фронт
            assert _wait(lambda: "CLEARED_AGAIN" in _marks(tmp_path), 10.0), (
                f"ребёнок не увидел clear(): {_marks(tmp_path)}"
            )
        finally:
            try:
                registry.stop_all(timeout=5.0)
            finally:
                if process.is_alive():
                    process.kill()
                process.join(timeout=5.0)

    _in_daemon(scenario, 100.0)


# --------------------------------------------------------------------------- #
# runner: атрибут до initialize(), None не затирает
# --------------------------------------------------------------------------- #

_NOT_SET = "MISSING"
_PRESET = object()


class _InitProbe:
    """Фиксирует, что лежало в ``_run_event`` к моменту ``initialize()`` и ``run()``. Атрибута у класса нет (фантом)."""

    at_initialize: list = []
    at_run: list = []
    preset: Any = _NOT_SET

    def __init__(self, name, shared_resources, config) -> None:
        self.name = name
        if _InitProbe.preset is not _NOT_SET:
            self._run_event = _InitProbe.preset

    def initialize(self) -> bool:
        _InitProbe.at_initialize.append(getattr(self, "_run_event", _NOT_SET))
        return True

    def run(self) -> None:
        _InitProbe.at_run.append(getattr(self, "_run_event", _NOT_SET))

    def should_stop(self) -> bool:
        return True


def _run_probe(**kwargs: Any) -> None:
    _InitProbe.at_initialize = []
    _InitProbe.at_run = []
    bundle = {"queues": {}, "config": {}, "custom": {}}

    def go() -> None:
        with patch(f"{_RUNNER_MOD}._load_process_class", return_value=_InitProbe):
            run_process_function("fake.Probe", "run_evt_probe", multiprocessing.Event(), bundle, **kwargs)

    thread = threading.Thread(target=go, daemon=True, name="run-evt-runner")
    thread.start()
    thread.join(timeout=20.0)
    assert not thread.is_alive(), "run_process_function не завершился за 20 с"


@pytest.mark.timeout(60)
def test_runner_sets_run_event_before_initialize() -> None:
    """Событие передано -> стоит к ``initialize()``; ``run_event=None`` -> предустановленное значение сохранено."""
    # keyword-only (позиционный шестой аргумент — new_session)
    params = inspect.signature(run_process_function).parameters
    assert "run_event" in params, sorted(params)
    param = params["run_event"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is None

    # случай 1: событие передано (атрибута у класса нет — опечатка в имени не даст молча None)
    _InitProbe.preset = _NOT_SET
    ev = multiprocessing.Event()
    _run_probe(run_event=ev)
    assert _InitProbe.at_initialize == [ev], _InitProbe.at_initialize
    assert _InitProbe.at_run == [ev], _InitProbe.at_run

    # случай 2: run_event=None, у экземпляра уже стоит свой _run_event — раннер его не затирает
    _InitProbe.preset = _PRESET
    try:
        _run_probe(run_event=None)
        assert _InitProbe.at_initialize == [_PRESET], _InitProbe.at_initialize
        assert _InitProbe.at_run == [_PRESET], _InitProbe.at_run
        # и без аргумента вовсе (PM спавнится без реестра) — то же
        _run_probe()
        assert _InitProbe.at_initialize == [_PRESET], _InitProbe.at_initialize
    finally:
        _InitProbe.preset = _NOT_SET
