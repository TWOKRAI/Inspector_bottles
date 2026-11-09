# -*- coding: utf-8 -*-
"""Task 1.4 (gui-graceful-close): авторские hazard-тесты ``pre_stop`` (ACCEPTANCE h1–h4, ADR-PMM-044).

PM — двойник из ``__new__`` (``conftest.make_pm``) + настоящие помощники хода стопа и шагов; роутер — фейк
``request_async``, который запоминает колбэки и отвечает по сценарию теста. Всё, что может повиснуть, —
в daemon-потоке с ``join`` по сроку.

  h1 — нет ``executor_manager``: ERROR, ответ ``phase: "children"``, события сразу, потоков ``pm-pre-stop`` нет;
  h2 — запоздавший ответ шага: колбэк закрытого шага — no-op, повтора шага нет, СЛЕДУЮЩИЙ шаг не тронут;
  h3 — гонка ``force``-эскалации и ``finally`` потока шагов: переход ``pre_stop → children`` один,
       ``deadline_at`` = срок ``force``, повторный вызов — no-op;
  h4 — PM из ``__new__`` без ``initialize``: ``system.shutdown`` и ``supervision.status`` не падают.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable
from unittest.mock import MagicMock

from ..core.stop_budget import stop_budget
from ..process.pre_stop import PreStopStep
from ..process.process_manager_process import _ChildrenStop
from .conftest import make_pm


class _Group:
    def request_stop(self) -> None:
        pass

    def join_until(self, deadline: float) -> bool:
        return True

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def result(self) -> dict[str, bool]:
        return {}


class _Router:
    """Фейк ``request_async``: записывает (сообщение, колбэк); ``on_request`` — сценарий теста."""

    def __init__(self, on_request: Callable[["_Router", dict, Callable], None] | None = None) -> None:
        self.requests: list[tuple[dict, Callable]] = []
        self._on_request = on_request

    def request_async(self, message: dict, on_response: Callable, timeout: float = 5.0) -> str:
        self.requests.append((message, on_response))
        if self._on_request is not None:
            self._on_request(self, message, on_response)
        return "cid"


def _pm(*, pre_stop: list | None = None, router: _Router | None = None, children_stop: bool = True) -> Any:
    pm = make_pm()
    pm.config = {"pre_stop": pre_stop} if pre_stop is not None else {}
    pm.config_handler = None
    pm.get_config = lambda key, default=None: pm.config.get(key, default)  # make_pm подменяет get_config
    pm.attach_stop_budget(stop_budget(5.0))
    pm.stop_event = threading.Event()
    pm._system_stop_event = threading.Event()
    pm.warnings, pm.errors, pm.infos = [], [], []
    pm._log_warning = lambda msg, *a, **k: pm.warnings.append(str(msg))
    pm._log_error = lambda msg, *a, **k: pm.errors.append(str(msg))
    pm._log_info = lambda msg, *a, **k: pm.infos.append(str(msg))
    registry = MagicMock()
    registry.get_process_by_name = MagicMock(return_value=object())
    registry.get_ready_event = MagicMock(return_value=None)
    registry.children_stop = MagicMock(return_value=_Group())
    pm._process_registry = registry
    pm._process_monitor = None
    pm._children_stop = _ChildrenStop(pm) if children_stop else None
    pm.router_manager = router or _Router()
    return pm


def _steps(*specs: tuple[str, str, float]) -> tuple[PreStopStep, ...]:
    return tuple(PreStopStep(process=p, command=c, timeout_s=t) for p, c, t in specs)


def _run_in_thread(fn: Callable[[], Any], deadline_s: float) -> threading.Thread:
    th = threading.Thread(target=fn, daemon=True, name="t14-author")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов завис дольше {deadline_s} с"
    return th


# --------------------------------------------------------------------------- #
# h1
# --------------------------------------------------------------------------- #


def test_h1_no_executor_manager_error_children_phase_events_now_no_threads() -> None:
    pm = _pm(pre_stop=[{"process": "arm", "command": "robot.home", "timeout_s": 5}])
    assert getattr(pm, "executor_manager", None) is None
    pm._setup_pre_stop()
    assert pm.errors == ["pre_stop: исполнитель недоступен — шаги отключены"], pm.errors
    assert pm._pre_stop_steps == ()

    box: dict[str, Any] = {}
    _run_in_thread(lambda: box.update(reply=pm._cmd_system_shutdown(None)), 2.0)
    reply = box["reply"]
    assert reply["accepted"] is True and reply["phase"] == "children", reply
    assert (pm.stop_event.is_set(), pm._system_stop_event.is_set()) == (True, True)
    assert pm.router_manager.requests == []
    assert [t.name for t in threading.enumerate() if "pm-pre-stop" in t.name] == []


# --------------------------------------------------------------------------- #
# h2
# --------------------------------------------------------------------------- #


def test_h2_late_reply_of_closed_step_is_noop_next_step_untouched() -> None:
    """1-й шаг молчит (0,2 с) и закрывается по ``timeout``; на запросе 2-го фейк сначала зовёт ОПОЗДАВШИЙ
    колбэк 1-го с ``success: True``, затем через 0,1 с отвечает 2-му ``success: False``. Ожидание: 1-й — ``timeout``,
    2-й — ``ошибка ответа`` (успех опоздавшего не достался 2-му), запросов ровно 2, колбэк 1-го не бросает."""
    late: dict[str, Any] = {}

    def on_request(router: _Router, message: dict, callback: Callable) -> None:
        if message["command"] == "s1":
            late["cb"] = callback
            return
        late["result"] = late["cb"]({"type": "response", "success": True, "result": {}})
        threading.Timer(0.1, lambda: callback({"type": "response", "success": False, "result": {}})).start()

    router = _Router(on_request)
    pm = _pm(router=router)
    pm._pre_stop_steps = _steps(("p1", "s1", 0.2), ("p2", "s2", 2.0))
    assert pm._begin_system_stop("graceful", "unknown", None, phase="pre_stop", window_s=2.2)

    _run_in_thread(pm._run_pre_stop, 5.0)

    assert [m["command"] for m, _cb in router.requests] == ["s1", "s2"]
    assert late["result"] is None
    assert pm.warnings == ["pre_stop: шаг 'p1.s1' — timeout", "pre_stop: шаг 'p2.s2' — ошибка ответа"], pm.warnings
    # Второй опоздавший вызов того же колбэка после конца списка — тоже no-op.
    late["cb"]({"type": "response", "success": True})
    assert len(pm.warnings) == 2
    assert (pm.stop_event.is_set(), pm._system_stop_event.is_set()) == (True, True)


# --------------------------------------------------------------------------- #
# h3
# --------------------------------------------------------------------------- #


def test_h3_force_escalation_races_steps_finally_single_transition_force_deadline() -> None:
    router = _Router()  # молчит: шаг ждёт до отмены
    pm = _pm(router=router)
    pm._pre_stop_steps = _steps(("p1", "s1", 30.0), ("p2", "s2", 5.0))
    assert pm._begin_system_stop("graceful", "unknown", None, phase="pre_stop", window_s=35.0)

    transitions: list[bool] = []
    original = pm._leave_pre_stop
    gate = threading.Barrier(2, timeout=5.0)

    def leave() -> bool:
        # Оба вызывающих (поток приёма force и finally потока шагов) входят одновременно.
        if threading.current_thread().name in ("t14-steps", "t14-force"):
            try:
                gate.wait()
            except threading.BrokenBarrierError:
                pass
        result = original()
        transitions.append(result)
        return result

    pm._leave_pre_stop = leave
    steps = threading.Thread(target=pm._run_pre_stop, daemon=True, name="t14-steps")
    steps.start()
    assert _wait(lambda: len(router.requests) == 1, 2.0), "1-й шаг не начался"

    box: dict[str, Any] = {}
    t_before = time.time()
    force = threading.Thread(
        target=lambda: box.update(reply=pm._cmd_system_shutdown({"mode": "force", "deadline_s": 1.0})),
        daemon=True,
        name="t14-force",
    )
    force.start()
    force.join(5.0)
    steps.join(5.0)
    t_after = time.time()
    assert not force.is_alive() and not steps.is_alive()

    assert box["reply"]["accepted"] is True and box["reply"]["escalated"] is True, box["reply"]
    assert transitions.count(True) == 1, transitions
    snap = pm._system_stop_snapshot()
    assert snap["phase"] == "children" and snap["pre_stop_step"] is None and snap["mode"] == "force", snap
    assert t_before + 1.0 - 0.05 <= snap["deadline_at"] <= t_after + 1.0 + 0.05, (snap, t_before, t_after)
    assert [m["command"] for m, _cb in router.requests] == ["s1"]
    assert "pre_stop: шаг 'p1.s1' прерван (force)" in pm.infos, pm.infos

    # Повторный вызов — no-op: ни перехода, ни сдвига срока.
    deadline_at = snap["deadline_at"]
    assert original() is False
    assert pm._system_stop_snapshot()["deadline_at"] == deadline_at


def _wait(predicate: Callable[[], bool], timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


# --------------------------------------------------------------------------- #
# h4
# --------------------------------------------------------------------------- #


def test_h4_bare_new_double_shutdown_and_status_do_not_fail() -> None:
    """PM из ``__new__`` без ``initialize`` и без новых атрибутов экземпляра (шаги, флаг отмены, исполнитель)."""
    graceful = make_pm()
    graceful.stop_event = threading.Event()
    graceful._system_stop_event = threading.Event()
    for attr in ("_pre_stop_steps", "_pre_stop_executor", "_pre_stop_cancel_obj", "_pre_stop_cancel_reason"):
        assert attr not in graceful.__dict__, attr
    box: dict[str, Any] = {}
    _run_in_thread(lambda: box.update(reply=graceful._cmd_system_shutdown(None)), 2.0)
    assert box["reply"]["accepted"] is True and box["reply"]["phase"] == "children", box["reply"]
    _run_in_thread(lambda: box.update(status=graceful._cmd_supervision_status({})), 2.0)
    assert box["status"]["system_stop"]["phase"] == "children", box["status"]
    assert graceful._lifecycle_rejected() is True  # события взведены — PM гасится

    forced = make_pm()  # без ``_children_stop`` и без событий: запасной путь force
    forced.stop_event = threading.Event()
    _run_in_thread(lambda: box.update(force=forced._cmd_system_shutdown({"mode": "force"})), 2.0)
    assert box["force"]["accepted"] is True and box["force"]["mode"] == "graceful", box["force"]
    assert forced._pre_stop_cancel_source() == "force"
    _run_in_thread(lambda: box.update(status2=forced._cmd_supervision_status({})), 2.0)
    assert box["status2"]["success"] is True


# --------------------------------------------------------------------------- #
# h5 — выход из pre_stop не потоком шагов (ревью r1, M2; инъекция Z)
# --------------------------------------------------------------------------- #


def test_h5_phase_change_out_of_pre_stop_clears_step_and_rebases_graceful_only() -> None:
    """Корневой стоп (``_ChildrenStop.request_stop`` → ``_set_system_stop_phase("children")``) во время шага:
    ``pre_stop_step is None``; graceful — ``deadline_at − now`` в [4,8; 5,0] (pm_graceful 5,0);
    ``force`` — срок прежний."""
    graceful = _pm()
    assert graceful._begin_system_stop("graceful", "unknown", None, phase="pre_stop", window_s=60.0)
    graceful._set_pre_stop_step("p1.home")
    _run_in_thread(graceful._children_stop.request_stop, 5.0)
    snap = graceful._system_stop_snapshot()
    assert snap["phase"] == "children" and snap["pre_stop_step"] is None, snap
    remaining = snap["deadline_at"] - time.time()
    assert 4.8 <= remaining <= 5.0, remaining
    # Поток шагов после такого выхода — no-op перехода.
    assert graceful._leave_pre_stop() is False

    forced = _pm()
    assert forced._begin_system_stop("graceful", "unknown", None, phase="pre_stop", window_s=60.0)
    assert forced._escalate_system_stop("force", 1.0)
    force_deadline = forced._system_stop_snapshot()["deadline_at"]
    forced._set_pre_stop_step("p1.home")
    forced._set_system_stop_phase("children")
    snap = forced._system_stop_snapshot()
    assert snap["phase"] == "children" and snap["pre_stop_step"] is None, snap
    assert snap["deadline_at"] == force_deadline, (snap, force_deadline)


# --------------------------------------------------------------------------- #
# h6 — свой stop_event PM без общего события отменяет шаг (ревью r1, открытое)
# --------------------------------------------------------------------------- #


def test_h6_own_stop_event_without_system_event_cancels_step() -> None:
    router = _Router()  # молчит: шаг ждёт до отмены
    pm = _pm(router=router)
    pm._pre_stop_steps = _steps(("p1", "s1", 30.0), ("p2", "s2", 5.0))
    assert pm._begin_system_stop("graceful", "unknown", None, phase="pre_stop", window_s=35.0)
    steps = threading.Thread(target=pm._run_pre_stop, daemon=True, name="t14-steps")
    steps.start()
    assert _wait(lambda: len(router.requests) == 1, 2.0), "1-й шаг не начался"

    t0 = time.monotonic()
    pm.stop_event.set()  # раннер/спавнер: только свой stop_event, общий не взведён
    assert _wait(lambda: pm._system_stop_snapshot()["phase"] == "children", 0.1), pm._system_stop_snapshot()
    elapsed = time.monotonic() - t0
    steps.join(2.0)
    assert not steps.is_alive()
    assert elapsed <= 0.1, elapsed
    assert pm._system_stop_snapshot()["pre_stop_step"] is None
    assert pm._system_stop_event.is_set()
    assert [m["command"] for m, _cb in router.requests] == ["s1"]
    assert "pre_stop: шаг 'p1.s1' прерван (event)" in pm.infos, pm.infos

    # Начатый стоп детей (без событий) — тот же источник отмены.
    other = _pm()
    assert other._pre_stop_cancel_source() is None
    other._children_stopping = True
    assert other._pre_stop_cancel_source() == "event"
