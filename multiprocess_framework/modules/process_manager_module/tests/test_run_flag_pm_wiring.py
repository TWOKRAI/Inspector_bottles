# -*- coding: utf-8 -*-
"""Task 1.10 (system-run-state) — проводка ``RunFlag`` в ProcessManager (REDS 6 и 7).

Контракт — ``plans/2026-10-27_system-run-state/tasks/1.10.md``: ``pm._run_event`` — ``RunFlag`` (не
``multiprocessing.Event``: у того каждое обращение берёт межпроцессный замок, F3); ``run_gate: false`` — взведён
сразу, ``run_gate: true`` — снят до ``system.run.start``; START взводит, STOP снимает; тот же объект уходит в
``ProcessRegistry(run_event=...)`` и через kwargs ``Process`` видим ребёнку в обе стороны (настоящий spawn).

Ожидания — литералы. Каждый блокирующий вызов — в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ..core.process_registry import ProcessRegistry
from ..core.run_flag import RunFlag
from .conftest import make_monitor_double, make_pm

_PM_MOD = "multiprocess_framework.modules.process_manager_module.process.process_manager_process"
_THIS = "multiprocess_framework.modules.process_manager_module.tests.test_run_flag_pm_wiring"
_SPAWN_DEADLINE_S = 30.0
_EDGE_DEADLINE_S = 10.0


def _make_pm_with_components(run_gate: bool) -> tuple[Any, Any]:
    """PM с настоящим ``_create_components()``; ``ProcessRegistry`` подменён, вторым — его мок-класс."""
    pm = make_pm()
    pm.update_config("run_gate", run_gate)
    with (
        patch(f"{_PM_MOD}.ProcessRegistry") as reg_cls,
        patch(f"{_PM_MOD}.ProcessPriority"),
        patch(f"{_PM_MOD}.ProcessStatusMonitor"),
        patch(f"{_PM_MOD}.ProcessMonitor", return_value=make_monitor_double()),
        patch(f"{_PM_MOD}.QueueRegistry"),
    ):
        pm._create_components()
    return pm, reg_cls


# --------------------------------------------------------------------------- #
# REDS 6: PM-wiring
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [True, False])
def test_pm_run_event_is_run_flag_not_mp_event(run_gate: bool) -> None:
    """``type(pm._run_event) is RunFlag`` — точный тип, не ``multiprocessing.Event`` и не подкласс."""
    pm, _reg = _make_pm_with_components(run_gate)
    assert type(pm._run_event) is RunFlag, type(pm._run_event)


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [True, False])
def test_pm_hands_same_run_flag_to_registry(run_gate: bool) -> None:
    """В ``ProcessRegistry(run_event=...)`` уходит тот же объект ``RunFlag``, что лежит в ``pm._run_event``."""
    pm, reg_cls = _make_pm_with_components(run_gate)
    handed = reg_cls.call_args.kwargs.get("run_event")
    assert handed is pm._run_event, reg_cls.call_args
    assert type(handed) is RunFlag, type(handed)


@pytest.mark.timeout(60)
def test_run_gate_false_flag_is_set_at_creation() -> None:
    pm, _reg = _make_pm_with_components(False)
    assert pm._run_event.is_set() is True, "run_gate false: флаг взведён сразу"


@pytest.mark.timeout(60)
def test_run_gate_true_flag_is_clear_until_start() -> None:
    pm, _reg = _make_pm_with_components(True)
    assert pm._run_event.is_set() is False, "run_gate true: флаг снят при создании"
    pm._run_apply("settled", ready=True)
    assert pm._run_state == "ready"
    assert pm._run_event.is_set() is False, "run_gate true: после boot флаг всё ещё снят до system.run.start"


@pytest.mark.timeout(60)
def test_run_gate_true_start_sets_and_stop_clears() -> None:
    pm, _reg = _make_pm_with_components(True)
    pm._run_apply("settled", ready=True)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    assert pm._run_event.is_set() is True, "START взводит флаг"
    assert pm._cmd_system_run_stop()["accepted"] is True
    assert pm._cmd_system_run_status()["state"] == "ready"
    assert pm._run_event.is_set() is False, "STOP снимает флаг"


# --------------------------------------------------------------------------- #
# REDS 7: сквозной, настоящие объекты, настоящий spawn
# --------------------------------------------------------------------------- #


class FlagChild:
    """Процесс-ребёнок: пишет в ``marks.txt`` тип полученного ``_run_event`` и фронты.

    Метки: ``type=<имя класса>``; ``CLEAR_SEEN`` (снято на старте), ``SET_SEEN`` (после снятого увидел взведённое),
    ``CLEARED_AGAIN`` (после взведённого снова увидел снятое). Только ``is_set()`` — писатель один, PM.
    """

    def __init__(self, name: str, shared_resources, config) -> None:
        self.name = name
        self._dir = Path(os.environ["RUN_FLAG_DIR"])
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
        flag = getattr(self, "_run_event", None)
        self._mark(f"type={type(flag).__name__}")
        if flag is not None:
            threading.Thread(target=self._watch, args=(flag,), daemon=True, name="run-flag-watch").start()
        if self._own_ready is not None:
            self._own_ready.set()

    def _watch(self, flag) -> None:
        phase = "want_clear"
        while not self._stop.is_set():
            is_set = flag.is_set()
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

    th = threading.Thread(target=go, daemon=True, name="run-flag-scenario")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"сценарий завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]


@pytest.mark.timeout(120)
def test_pm_run_flag_through_registry_child_sees_start_and_stop(tmp_path, monkeypatch) -> None:
    """PM (``run_gate: true``) -> ``ProcessRegistry(run_event=pm._run_event)`` -> kwargs ``Process`` -> ребёнок.

    START PM взводит флаг (ребёнок видит True), STOP снимает (ребёнок видит False); тип у ребёнка — ``RunFlag``.
    """
    monkeypatch.setenv("RUN_FLAG_DIR", str(tmp_path))

    def scenario() -> None:
        pm, _reg = _make_pm_with_components(True)
        pm._run_apply("settled", ready=True)
        assert type(pm._run_event) is RunFlag, type(pm._run_event)
        assert pm._run_event.is_set() is False

        registry = ProcessRegistry(logger=None, run_event=pm._run_event)
        process = registry.create_and_register("run_flag_child", f"{_THIS}.FlagChild", {}, "normal")
        assert process is not None, "create_and_register вернул None"
        try:
            process.start()
            own_ready = registry.get_ready_event("run_flag_child")
            assert own_ready is not None
            assert own_ready.wait(_SPAWN_DEADLINE_S), (
                f"ребёнок не объявил готовность за {_SPAWN_DEADLINE_S} с "
                f"(alive={process.is_alive()}, exitcode={process.exitcode}, marks={_marks(tmp_path)})"
            )
            assert "type=RunFlag" in _marks(tmp_path), _marks(tmp_path)
            assert _wait(lambda: "CLEAR_SEEN" in _marks(tmp_path), _EDGE_DEADLINE_S), _marks(tmp_path)
            assert "SET_SEEN" not in _marks(tmp_path)

            assert pm._cmd_system_run_start() == {"success": True, "state": "running"}  # передний фронт — после спавна
            assert _wait(lambda: "SET_SEEN" in _marks(tmp_path), _EDGE_DEADLINE_S), (
                f"ребёнок не увидел START: {_marks(tmp_path)}"
            )
            assert pm._cmd_system_run_stop()["accepted"] is True  # задний фронт
            assert _wait(lambda: "CLEARED_AGAIN" in _marks(tmp_path), _EDGE_DEADLINE_S), (
                f"ребёнок не увидел STOP: {_marks(tmp_path)}"
            )
        finally:
            try:
                registry.stop_all(timeout=5.0)
            finally:
                if process.is_alive():
                    process.kill()
                process.join(timeout=5.0)

    _in_daemon(scenario, 100.0)
