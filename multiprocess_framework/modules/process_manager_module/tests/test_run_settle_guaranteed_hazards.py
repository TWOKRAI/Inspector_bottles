# -*- coding: utf-8 -*-
"""fix-A3 (свежее ревью Ф1, F2 / совет С1) — итог ``settled`` гарантирован конструкцией.

У ``booting`` и ``stopping`` выход — только ``settled`` (или ``shutdown``). Оценка готовности, бросившая ОДИН раз в
итоге подъёма/применения или в итоге STOP, не оставляет машину там навсегда: итог — ``not_ready`` с причиной
``failure`` «оценка готовности не удалась» и ERROR в журнале; следующие чистые такты возвращают ``ready``.

Обвязка — ``make_readiness_pm`` (настоящие PM и ``ProcessMonitor``). Значения — литералы; ожидание — с дедлайном.
"""

from __future__ import annotations

from typing import Any

import pytest

from .conftest import make_pm
from .test_run_commands import _to_running, beat, make_readiness_pm, tick
from .test_run_stop import _DEADLINE_S, _beat, _wait

_EVAL_FAILED = {
    "node": "ProcessManager",
    "severity": "failure",
    "source": "report",
    "reason": "оценка готовности не удалась",
}
_EVAL_FAILED_LOG = "readiness: оценка готовности не удалась (RuntimeError)"


def _fail_next_evaluation(pm: Any) -> list[str]:
    """Следующая оценка готовности бросает ``RuntimeError`` один раз; дальше — настоящая."""
    original = pm._evaluate_run_readiness
    raised: list[str] = []

    def evaluate(**kwargs: Any) -> Any:
        if not raised:
            raised.append("raised")
            raise RuntimeError("boom")
        return original(**kwargs)

    pm._evaluate_run_readiness = evaluate
    return raised


def _state(pm: Any) -> str:
    return pm._run_snapshot()[0].value


def _errors(pm: Any) -> list[str]:
    return [c.args[0] for c in pm._log_error.call_args_list if c.args]


@pytest.mark.timeout(60)
def test_settle_evaluation_failure_after_apply_leaves_booting() -> None:
    pm, monitor = make_readiness_pm({"cam": {"class": "X"}})
    beat(monitor, "cam")
    tick(pm, monitor)
    pm._run_apply("apply")
    assert _state(pm) == "booting"
    raised = _fail_next_evaluation(pm)

    escaped: list[str] = []
    try:
        pm._settle_run_state()  # так его зовёт ``finally`` у ``topology.apply``
    except RuntimeError as exc:
        escaped.append(type(exc).__name__)

    assert raised == ["raised"]
    assert _state(pm) == "not_ready"
    assert pm._cmd_system_run_status()["reasons"] == [_EVAL_FAILED]
    assert _errors(pm) == [_EVAL_FAILED_LOG]
    assert escaped == []

    pm._log_error.reset_mock()
    for _ in range(3):
        beat(monitor, "cam")
        tick(pm, monitor)
    assert _state(pm) == "ready"


@pytest.mark.timeout(60)
def test_evaluation_before_configs_loaded_does_not_raise() -> None:
    """PM до загрузки конфигов (атрибута ``_process_configs`` ещё нет, как у PM из ``__new__`` до ``initialize``):
    оценка готовности не бросает и даёт пустой набор — готов, причин нет (регресс fix-B2/N2)."""
    pm = make_pm()
    del pm._process_configs

    assert pm._evaluate_run_readiness() == (True, [])


@pytest.mark.timeout(60)
def test_stop_finish_evaluation_failure_leaves_stopping() -> None:
    pm, monitor = make_readiness_pm({"cam": {"class": "X"}})
    _to_running(pm, monitor)
    assert pm._cmd_system_run_stop() == {"success": True, "accepted": True, "state": "stopping"}
    raised = _fail_next_evaluation(pm)

    _beat(monitor, "cam", ready=True, reasons=[], paused=True, age_s=0.0)  # ребёнок встал на паузу

    assert _wait(lambda: _state(pm) != "stopping", _DEADLINE_S), "машина осталась в stopping"
    assert raised == ["raised"]
    assert _state(pm) == "not_ready"
    assert pm._cmd_system_run_status()["reasons"] == [_EVAL_FAILED]
    assert _errors(pm) == [_EVAL_FAILED_LOG]

    pm._log_error.reset_mock()
    for _ in range(3):
        beat(monitor, "cam")
        tick(pm, monitor)
    assert _state(pm) == "ready"
