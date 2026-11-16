"""Приёмка (слепая): причина ``check_function`` не прячется синтезированной причиной ``failure``.

Процесс сообщает «не готов» с причиной степени ``check_function`` («камера открывается»). Оператор должен видеть
именно её; лишней причины ``failure`` «<процесс> не готов» (источник ``report``) быть не должно. Блокирующие
степени везде одни и те же.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.process.run_state import (
    BLOCKING_SEVERITIES,
    EvalInput,
    evaluate,
    restart_window,
)
from multiprocess_framework.modules.process_module.health.schema import READINESS_BLOCKING_SEVERITIES

from .test_run_commands import beat, make_readiness_pm, tick

R = {"node": "cam.cam", "severity": "check_function", "reason": "камера открывается", "source": "readiness"}


def _call_with_deadline(fn: Any, deadline_s: float = 20.0) -> Any:
    """Вызов в daemon-потоке с join-дедлайном: зависание = красный тест, не зависший прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["error"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(deadline_s)
    assert not t.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _leaf(at: float) -> dict:
    return {"ready": False, "reasons": [dict(R)], "paused": False, "at": at}


def test_check_function_reason_is_not_hidden_by_synthesized_failure() -> None:
    """Живой процесс со свежим листом ``ready: false`` и единственной причиной ``check_function``:
    итог ``(False, [R])`` — без добавленной причины ``failure`` «cam не готов»."""
    inp = EvalInput(
        expected=["cam"],
        leaves={"cam": _leaf(100.0)},
        alive={"cam": True},
        now=100.0,
        stale_s=5.0,
    )

    result = _call_with_deadline(lambda: evaluate(inp))

    assert result == (False, [R])


def test_restart_window_reason_unchanged_for_stale_leaf_of_auto_restart_process() -> None:
    """Контроль: процесс с автоперезапуском в окне ``grace_s`` по-прежнему даёт только причину перезапуска
    ``out_of_spec`` и открытое окно с отметкой ``down_since``."""
    inp = EvalInput(
        expected=["cam"],
        leaves={"cam": _leaf(105.0)},
        alive={"cam": True},
        now=105.0,
        stale_s=5.0,
        running=True,
        auto_restart=frozenset({"cam"}),
        down_since={"cam": 100.0},
        grace_s=30.0,
    )

    result = _call_with_deadline(lambda: evaluate(inp))
    window = _call_with_deadline(lambda: restart_window(inp))

    assert result == (
        True,
        [{"node": "cam", "severity": "out_of_spec", "reason": "перезапуск cam", "source": "liveness"}],
    )
    assert window == {"cam": 100.0}


@pytest.mark.timeout(60)
def test_run_status_shows_check_function_reason_without_synthesized_failure() -> None:
    """PM: процесс отчитался ``ready: false`` с причиной ``check_function`` -> такт -> в ``system.run.status``
    есть текст «камера открывается» и нет «cam не готов»."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})

    beat(monitor, "cam", ready=False, reasons=[dict(R)])
    tick(pm, monitor)

    texts = [r["reason"] for r in pm._cmd_system_run_status()["reasons"]]
    assert any("камера открывается" in t for t in texts), texts
    assert not any("cam не готов" in t for t in texts), texts


def test_blocking_severities_are_failure_and_check_function_everywhere() -> None:
    """Контроль: блокирующие степени — ровно ``failure`` и ``check_function`` и в оценке, и в схеме здоровья."""
    assert BLOCKING_SEVERITIES == frozenset({"failure", "check_function"})
    assert set(READINESS_BLOCKING_SEVERITIES) == {"failure", "check_function"}
