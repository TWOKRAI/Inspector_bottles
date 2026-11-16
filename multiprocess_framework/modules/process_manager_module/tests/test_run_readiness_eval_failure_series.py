# -*- coding: utf-8 -*-
"""fix-B4 / сбой оценки готовности на такте (совет свежего ревью Ф1 run-state): серия, а не потерянный такт.

Раньше исключение из оценки терялось на такте: ERROR на каждом такте (~2 Гц), состояние не менялось, причины не
обновлялись. Теперь подряд идущие сбои — серия: ERROR один раз на серию; в статусе причина ``failure`` «оценка
готовности не удалась»; пока серия короче срока молчания (``3 x`` интервал heartbeat), состояние держится (одиночный
сбой не даёт дребезга); серия не короче срока — то же молчание, что «нет отчёта о готовности»: в ``running`` это
``fault``. Первый успешный такт серию сбрасывает.

Порог — литерал: интервал heartbeat 0.1 с -> срок молчания 0.3 с. Обвязка — настоящие PM + монитор.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from .test_run_commands import beat, make_readiness_pm

_REASON = "оценка готовности не удалась"
_STALE_S = 0.3  # 3 x heartbeat_interval 0.1 с


def _raw_tick(monitor: Any) -> None:
    with monitor._iteration_lock:
        monitor._run_iteration()


def _running_pm() -> tuple[Any, Any, dict]:
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    pm.update_config("heartbeat_interval", 0.1)
    pm.update_config("heartbeat_interval_sec", 0.1)
    assert pm._run_stale_s() == pytest.approx(_STALE_S)
    beat(monitor, "cam")
    _raw_tick(monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}

    original = pm._evaluate_run_readiness
    mode = {"fail": False}

    def evaluate(**kwargs: Any) -> Any:
        if mode["fail"]:
            raise ValueError("SECRET-boom")
        return original(**kwargs)

    pm._evaluate_run_readiness = evaluate
    pm._log_error.reset_mock()
    return pm, monitor, mode


def _fail_errors(pm: Any) -> list[str]:
    return [c.args[0] for c in pm._log_error.call_args_list if c.args and _REASON in c.args[0]]


@pytest.mark.timeout(60)
def test_short_failure_series_keeps_running_one_error_and_reason_in_status() -> None:
    """Три сбоя подряд быстрее срока (0.3 с): ``running`` держится, ERROR один на всю серию (не три), в статусе одна
    причина ``failure`` «оценка готовности не удалась» (без текста исключения)."""
    pm, monitor, mode = _running_pm()
    mode["fail"] = True

    for _ in range(3):
        _raw_tick(monitor)

    assert pm._run_state == "running"
    assert len(_fail_errors(pm)) == 1, _fail_errors(pm)
    status = pm._cmd_system_run_status()
    assert [(r["severity"], r["reason"]) for r in status["reasons"]] == [("failure", _REASON)], status
    assert "SECRET" not in str(status["reasons"])


@pytest.mark.timeout(60)
def test_failure_series_not_shorter_than_stale_goes_fault() -> None:
    """Серия длится не меньше срока (0.3 с): следующий сбой — ``tick(ready=False)``, в ``running`` это ``fault``."""
    pm, monitor, mode = _running_pm()
    mode["fail"] = True

    _raw_tick(monitor)
    assert pm._run_state == "running"
    time.sleep(0.4)
    _raw_tick(monitor)

    assert pm._run_state == "fault", pm._run_state
    assert pm._run_event.is_set() is False
    assert [r["reason"] for r in pm._cmd_system_run_status()["reasons"]] == [_REASON]
    assert len(_fail_errors(pm)) == 1, _fail_errors(pm)


@pytest.mark.timeout(60)
def test_successful_tick_resets_the_series() -> None:
    """Сбой, пауза дольше срока, УСПЕШНЫЙ такт, снова сбой: серия началась заново — ``running`` (без сброса вторая
    серия считалась бы от первого сбоя и дала ``fault``), второй ERROR — новый, причина сбоя из статуса ушла после
    успеха."""
    pm, monitor, mode = _running_pm()
    mode["fail"] = True
    _raw_tick(monitor)
    time.sleep(0.4)

    mode["fail"] = False
    beat(monitor, "cam")
    _raw_tick(monitor)
    assert pm._run_state == "running"
    assert pm._cmd_system_run_status()["reasons"] == []

    mode["fail"] = True
    _raw_tick(monitor)

    assert pm._run_state == "running"
    assert len(_fail_errors(pm)) == 2, _fail_errors(pm)
