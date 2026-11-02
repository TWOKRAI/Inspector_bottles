# -*- coding: utf-8 -*-
"""C-64 — hazard-тесты автора: возврат статусов проводов и переигровка в откате.

Дополняют слепую приёмку (``test_wire_status_refused_switch_acceptance.py``): гонки с чужими записями в окне
переключения, ``unstoppable``, сбой переигровки, неготовый ребёнок, системный стоп. Обвязка — та же:
``make_pm`` (двойники процессов) + ``pm.send_message = MagicMock()`` + настоящий ``ProcessMonitor``.
Ожидаемые значения — литералы; всё, что может блокироваться, идёт в daemon-потоке с ``join``-дедлайном.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from .test_wire_status_refused_switch_acceptance import (
    WIRE_KEY,
    _apply,
    _configure_calls,
    _pm_with_wire,
    _published,
    _run_with_deadline,
    _wire_status,
)

STATE_BROKEN_PATH = "system.health.broken_wires"
APPLY_DEADLINE_S = 2.0  # apply_topology на двойниках с неготовым ребёнком не должен ждать готовности
POLL_DEADLINE_S = 5.0


def _fail_in_apply(pm: Any) -> None:
    """Исключение из ``TopologyManager.apply`` -> консервативный откат (процессы пересозданы)."""
    pm._topology_manager.apply = MagicMock(side_effect=RuntimeError("outside apply"))


def _set_commands_fn(pm: Any, fn: Callable[[dict, dict], list[dict]]) -> None:
    pm._topology_manager.configure(commands_fn=fn)


def _wait_until(predicate: Callable[[], bool], deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _error_lines(pm: Any) -> list[str]:
    return [str(call.args[0]) for call in pm._log_error.call_args_list]


def _arm_unready_children(pm: Any) -> dict[str, threading.Event]:
    """``ready_event`` обоих детей не взведён: ``wire.configure`` откладывается до готовности."""
    events = {"cam": threading.Event(), "proc": threading.Event()}
    pm._process_registry._ready_events.update(events)
    return events


def test_h1_teardown_in_window_does_not_resurrect_wire() -> None:
    """H1: провод разобран ``wire.teardown`` внутри ``commands_fn``, затем отказ -> провода нет, исключения нет."""
    pm = _pm_with_wire()

    def commands_fn(diff_result: dict, desired: dict) -> list[dict]:
        pm._cmd_wire_teardown(wire_key=WIRE_KEY)
        raise RuntimeError("BlueprintInvalid")

    _set_commands_fn(pm, commands_fn)

    result = _apply(pm)

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert pm._cmd_wire_status()["wires"] == {}, f"wire.status: {pm._cmd_wire_status()}"


def test_h2_wire_created_in_window_is_left_alone() -> None:
    """H2: ``wire.setup`` нового ключа внутри ``commands_fn`` + отказ -> новый ``active``, старый вернул ``active``."""
    pm = _pm_with_wire()

    def commands_fn(diff_result: dict, desired: dict) -> list[dict]:
        setup = pm._cmd_wire_setup(
            wire_key="proc->cam", source_process="proc", target_process="cam", transport="direct"
        )
        assert setup["success"] is True, f"wire.setup в окне: {setup}"
        raise RuntimeError("BlueprintInvalid")

    _set_commands_fn(pm, commands_fn)

    _apply(pm)

    wires = pm._cmd_wire_status()["wires"]
    assert wires[WIRE_KEY]["status"] == "active", f"wire.status: {wires}"
    assert wires["proc->cam"]["status"] == "active", f"wire.status: {wires}"


def test_h3_unstoppable_name_gets_no_configure_and_partner_reissues() -> None:
    """H3: ``stop_many`` не подтвердил ``cam`` при откате -> ``cam`` не пересоздан и не получает ``wire.configure``;
    ``proc`` пересоздан и получил ``receiver``; провод ``active``, ``broken_wires`` 0."""
    pm = _pm_with_wire()
    pm._process_registry.stop_many = lambda names, timeout=5.0, **kw: {n: n != "cam" for n in names}
    _fail_in_apply(pm)

    result = _apply(pm)

    assert result["rolled_back"] is True
    assert result["unstoppable"] == ["cam"], f"unstoppable: {result.get('unstoppable')}"
    assert _wire_status(pm) == "active"
    assert _published(pm).get(STATE_BROKEN_PATH) == 0
    assert _configure_calls(pm) == [("proc", "receiver")], f"wire.configure: {_configure_calls(pm)}"


def test_h4_reissue_failure_for_one_name_does_not_break_rollback() -> None:
    """H4: ``_reissue_wires_for('cam')`` бросает ``RuntimeError("boom")`` -> откат не прерван: ответ ``rolled_back``
    True, ``proc`` получил ``wire.configure``, ошибка в журнале дословно. Краснеет при снятии нового ``try/except``."""
    pm = _pm_with_wire()
    real = pm._reissue_wires_for

    def flaky(name: str) -> int:
        if name == "cam":
            raise RuntimeError("boom")
        return real(name)

    pm._reissue_wires_for = flaky
    _fail_in_apply(pm)

    result = _apply(pm)

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert _configure_calls(pm) == [("proc", "receiver")], f"wire.configure: {_configure_calls(pm)}"
    assert "rollback: wire re-issue 'cam' не удался: boom" in _error_lines(pm), _error_lines(pm)


def test_h4b_send_failure_is_swallowed_below_and_wire_stays_broken() -> None:
    """H4b (страж): ``send_message`` бросает -> откат завершён, провод ``broken``, ERROR от ``_send_wire_configure``.

    Зелёный и без нового ``except`` в откате: сбой отправки глотается ниже."""
    pm = _pm_with_wire()
    pm.send_message = MagicMock(side_effect=RuntimeError("down"))
    _fail_in_apply(pm)

    result = _apply(pm)

    assert result["rolled_back"] is True
    assert _wire_status(pm) == "broken"
    assert "wire re-issue 'cam->proc' в 'cam' не удался: down" in _error_lines(pm), _error_lines(pm)


def test_h5_unready_child_apply_returns_at_once_and_wire_returns_after_ready() -> None:
    """H5: ``ready_event`` не взведён при откате -> ``apply_topology`` вернулся без ожидания, провод ``broken``,
    ``wire.configure`` нет; после взвода событий — ``active`` и по одному ``wire.configure`` в каждого."""
    pm = _pm_with_wire()
    events = _arm_unready_children(pm)
    _fail_in_apply(pm)

    result = _run_with_deadline(lambda: pm.apply_topology({"processes": []}), APPLY_DEADLINE_S, "apply_topology")

    assert result["rolled_back"] is True
    assert _wire_status(pm) == "broken"
    assert _configure_calls(pm) == [], f"wire.configure до готовности: {_configure_calls(pm)}"

    for event in events.values():
        event.set()

    assert _wait_until(lambda: _wire_status(pm) == "active", POLL_DEADLINE_S), f"wire.status={_wire_status(pm)!r}"
    assert _wait_until(lambda: len(_configure_calls(pm)) == 2, POLL_DEADLINE_S), f"{_configure_calls(pm)}"
    assert _configure_calls(pm) == [("cam", "sender"), ("proc", "receiver")]


def test_h6_system_stop_during_rollback_sends_nothing_and_wire_stays_broken() -> None:
    """H6: ``_pm_stopping()`` при откате -> пересоздания нет, ``wire.configure`` нет, провод ``broken``."""
    pm = _pm_with_wire()
    pm._system_stop_event = threading.Event()
    pm._system_stop_event.set()
    assert pm._pm_stopping() is True
    _fail_in_apply(pm)

    _apply(pm)

    assert _configure_calls(pm) == [], f"wire.configure: {_configure_calls(pm)}"
    assert _wire_status(pm) == "broken"


def test_h7_foreign_active_write_in_window_is_not_overwritten() -> None:
    """H7: статус до вызова ``broken``; внутри ``commands_fn`` чужой поток (``ready-gate``) ставит ``active``, затем
    отказ -> возврат прежнего ``broken`` не затирает ``active``: ``wire.status`` ``active``, ``broken_wires`` 0."""
    pm = _pm_with_wire()
    pm._active_wires[WIRE_KEY]["status"] = "broken"

    def commands_fn(diff_result: dict, desired: dict) -> list[dict]:
        pm._active_wires[WIRE_KEY]["status"] = "active"
        raise RuntimeError("BlueprintInvalid")

    _set_commands_fn(pm, commands_fn)

    _apply(pm)

    assert _wire_status(pm) == "active"
    assert _published(pm).get(STATE_BROKEN_PATH) == 0


def test_h8_success_with_commands_keeps_broken_until_reissue() -> None:
    """H8: успех с исполненными командами, ребёнок не готов (отправка отложена) -> сразу после возврата ``broken``
    (возврат статуса сторожится условием «нет исполненных команд»); после взвода ``ready_event`` — ``active``."""
    pm = _pm_with_wire()
    events = _arm_unready_children(pm)

    result = _run_with_deadline(
        lambda: pm.apply_topology(
            {
                "processes": [
                    {"process_name": "cam", "process_class": "x.Cam"},
                    {"process_name": "proc", "process_class": "x.Proc"},
                ]
            }
        ),
        APPLY_DEADLINE_S,
        "apply_topology",
    )

    assert result["success"] is True
    assert result["applied"] > 0, f"applied={result.get('applied')!r}"
    assert _wire_status(pm) == "broken"
    assert _configure_calls(pm) == [], f"wire.configure до готовности: {_configure_calls(pm)}"

    for event in events.values():
        event.set()

    assert _wait_until(lambda: _wire_status(pm) == "active", POLL_DEADLINE_S), f"wire.status={_wire_status(pm)!r}"
