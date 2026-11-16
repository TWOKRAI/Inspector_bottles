# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 2.1 на ``BackendHarness.start_run`` (дополнение к слепой приёмке).

Что может сломаться в цикле «опрос status -> START» (ревью 2.1, итерация 1):
  * ``fault`` липкий: без ``run_ack`` ``running`` не наступит — ждать весь ``timeout`` бессмысленно;
  * START «принят, но running нет»: цикл не должен слать START на каждом опросе (~10/с);
  * ответ status без ``state`` (отказ, конверт ошибки) не должен выглядеть как «просто не готов»:
    сообщение несёт сырой ответ и число опросов без ``state``.
PM — заглушка-подкласс ``BackendDriver`` с подменённым ``request``; всё, что может зависнуть, — в
daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness


def _bounded(fn: Callable[[], Any], deadline_s: float = 20.0) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    return {"type": "response", "command": "process.command.response", "success": True, "result": result}


class _Pm(BackendDriver):
    """``status`` отдаёт заданный снимок; START только считается (состояние не меняется)."""

    def __init__(self, status: dict[str, Any] | None, raw: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._status = status
        self._raw = raw
        self.starts = 0
        self.status_polls = 0

    def request(self, message: dict, timeout: float | None = None) -> dict:  # type: ignore[override]
        cmd = message["data"]["cmd"]
        if cmd == "system.run.start":
            self.starts += 1
            return _ok({"success": True, "state": "ready"})  # «принят», но running нет
        self.status_polls += 1
        return self._raw if self._raw is not None else _ok(self._status or {})


def _harness(pm: _Pm) -> BackendHarness:
    harness = BackendHarness(port=8776)
    harness._driver = pm
    return harness


def test_fault_exits_at_once_with_state_and_last_fault() -> None:
    """``fault`` -> AssertionError сразу (не за ``timeout``), в тексте состояние, причина и last_fault."""
    pm = _Pm(
        {
            "state": "fault",
            "start_allowed": False,
            "reasons": ["cam_front: dead"],
            "last_fault": {"node": "cam_front", "kind": "liveness"},
        }
    )
    t0 = time.monotonic()

    with pytest.raises(AssertionError) as info:
        _bounded(lambda: _harness(pm).start_run(timeout=30.0), deadline_s=10.0)

    text = str(info.value)
    assert time.monotonic() - t0 < 5.0, "fault ждал таймаут вместо раннего выхода"
    assert "fault" in text and "cam_front" in text and "liveness" in text, text
    assert pm.starts == 0


def test_start_is_not_resent_faster_than_once_per_second() -> None:
    """START принят, ``running`` нет, ``start_allowed`` всё время true: за ~2,5 с — не более 3 START (было ~25)."""
    pm = _Pm({"state": "ready", "start_allowed": True, "reasons": [], "last_fault": None})

    with pytest.raises(AssertionError):
        _bounded(lambda: _harness(pm).start_run(timeout=2.5), deadline_s=20.0)

    assert 1 <= pm.starts <= 3, f"START ушёл {pm.starts} раз за 2,5 с"


def test_timeout_message_carries_raw_reply_and_stateless_poll_count() -> None:
    """Ответ без ``state`` (конверт ошибки): сообщение несёт сырой ответ и число таких опросов."""
    raw = {"type": "response", "command": "process.command.response", "success": False, "error": "pm_busy_boom"}
    pm = _Pm(None, raw=raw)

    with pytest.raises(AssertionError) as info:
        _bounded(lambda: _harness(pm).start_run(timeout=0.5), deadline_s=15.0)

    text = str(info.value)
    assert "pm_busy_boom" in text, text
    assert f"опросов={pm.status_polls}" in text and f"без state: {pm.status_polls}" in text, text
    assert pm.starts == 0
