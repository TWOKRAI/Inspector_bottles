# -*- coding: utf-8 -*-
"""Task 0.2 (gui-graceful-close): авторские тесты ``system.shutdown mode=force`` (замечания ревью).

Дополняют приёмку тестера (``test_system_shutdown_force.py``), её не трогают:
  * повторный ``force`` — ответ несёт ДЕЙСТВУЮЩИЙ срок (первый) и ``already_set``;
  * огромное целое ``deadline_s`` — ошибка аргумента, а не ``OverflowError``;
  * ``force`` без ``deadline_s`` — срок 1.0 с;
  * ``_children_stop is None`` — точный ответ graceful + WARNING;
  * ``graceful`` без ``mode`` — точный прежний ответ.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable
from unittest.mock import MagicMock, patch

from ..process.process_manager_process import ProcessManagerProcess, _ChildrenStop


class _Group:
    def __init__(self) -> None:
        self.join_deadlines: list[float] = []

    def request_stop(self) -> None:
        pass

    def join_until(self, deadline: float) -> bool:
        self.join_deadlines.append(deadline)
        return True

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def result(self) -> dict[str, bool]:
        return {}


def _pm(with_children_stop: bool = True) -> tuple[Any, _Group]:
    group = _Group()
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm.shared_resources = None
    pm.config = {}
    pm._process_monitor = None
    pm._process_registry = MagicMock()
    pm._process_registry.children_stop = MagicMock(return_value=group)
    pm._log_info = MagicMock()
    pm._log_warning = MagicMock()
    pm._log_error = MagicMock()
    pm._children_stop = _ChildrenStop(pm) if with_children_stop else None
    pm.stop_event = threading.Event()
    pm._system_stop_event = threading.Event()
    return pm, group


def _bounded(fn: Callable[[], Any], deadline_s: float = 5.0) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _info_lines(pm: Any) -> list[str]:
    return [str(call.args[0]) for call in pm._log_info.call_args_list if call.args]


def test_repeat_force_reply_carries_effective_deadline() -> None:
    pm, _ = _pm()
    first = _bounded(lambda: pm._cmd_system_shutdown({"mode": "force", "deadline_s": 1.0}))
    assert first == {"success": True, "message": "Shutdown initiated", "mode": "force", "deadline_s": 1.0}

    second = _bounded(lambda: pm._cmd_system_shutdown({"mode": "force", "deadline_s": 4.0}))
    assert second == {
        "success": True,
        "message": "Shutdown initiated",
        "mode": "force",
        "deadline_s": 1.0,
        "already_set": True,
    }, second
    assert any("force: срок уже стоит (1.0 с), повтор не меняет" in line for line in _info_lines(pm)), _info_lines(pm)


def test_huge_int_deadline_is_argument_error_not_overflow() -> None:
    pm, _ = _pm()
    reply = _bounded(lambda: pm._cmd_system_shutdown({"mode": "force", "deadline_s": 10**400}))
    assert reply == {"error": "deadline_s: 0.1..5.0"}, reply
    assert (pm.stop_event.is_set(), pm._system_stop_event.is_set()) == (False, False)
    assert pm._children_stop._force_at is None


def test_force_without_deadline_uses_default_one_second() -> None:
    pm, group = _pm()
    pm._children_stop.request_stop()
    t_before = time.monotonic()
    reply = _bounded(lambda: pm._cmd_system_shutdown({"mode": "force"}))
    t_after = time.monotonic()
    assert reply == {"success": True, "message": "Shutdown initiated", "mode": "force", "deadline_s": 1.0}, reply

    assert _bounded(lambda: pm._children_stop.join_until(time.monotonic() + 10.0)) is True
    passed = group.join_deadlines[0]
    assert t_before + 1.0 <= passed <= t_after + 1.0, (passed, t_before, t_after)


def test_force_without_children_stop_falls_back_to_graceful() -> None:
    pm, _ = _pm(with_children_stop=False)
    reply = _bounded(lambda: pm._cmd_system_shutdown({"mode": "force", "deadline_s": 1.0}))
    assert reply == {"success": True, "message": "Shutdown initiated", "mode": "graceful"}, reply
    assert pm._log_warning.call_count == 1, pm._log_warning.call_args_list
    assert (pm.stop_event.is_set(), pm._system_stop_event.is_set()) == (True, True)


def test_graceful_without_mode_exact_old_reply() -> None:
    pm, _ = _pm()
    reply = _bounded(lambda: pm._cmd_system_shutdown(None))
    assert reply == {"success": True, "message": "Shutdown initiated"}, reply
    assert (pm.stop_event.is_set(), pm._system_stop_event.is_set()) == (True, True)
    assert pm._children_stop._force_at is None
