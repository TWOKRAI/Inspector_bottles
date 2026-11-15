# -*- coding: utf-8 -*-
"""fix-B / M2 (ревью Ф1 run-state): один разборщик ``restart_policy`` для PM и супервизора.

Раньше PM читал сырой dict (``enabled is True``), монитор строил ``RestartPolicy(**dict)`` (pydantic): на негодном
или «приводимом» входе они расходились в обе стороны. Теперь PM берёт решённую политику у монитора, и «супервизор
перезапустит» судится одним разбором. Здесь на трёх входах ревьюера сверяются обе стороны по НАБЛЮДАЕМОМУ эффекту:

  * PM — причины готовности (``_evaluate_run_readiness`` / ``system.run.status``);
  * супервизор — поднял ли монитор перезапуск упавшего процесса (``restart_count`` снимка).

Обвязка — настоящие ``ProcessManagerProcess`` + ``ProcessMonitor`` (``make_readiness_pm``). Ожидания — литералы.
Контракт причин: значения входа в причину не попадают.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ..core.restart_policy import RestartPolicy
from .test_run_commands import beat, make_readiness_pm, tick

# backoff_sec огромный: монитор планирует рестарт (restart_count растёт), но в рамках теста не диспатчит его
_BACKOFF = 600.0
_CONFIG_REASON_TEXT = "restart_policy негоден: cam"


def _pm_with(restart_policy: dict) -> tuple[Any, Any]:
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam", "restart_policy": dict(restart_policy)}})
    beat(monitor, "cam")
    tick(pm, monitor)
    return pm, monitor


def _crash_and_tick(pm: Any, monitor: Any) -> None:
    """Процесс упал; такт монитора (без проверки «нет ошибок»: настоящий сбой пишет в журнал сам)."""
    proc = pm._process_registry.get_process_by_name("cam")
    proc._alive = False
    proc.exitcode = -9
    with monitor._iteration_lock:
        monitor._run_iteration()


def _restart_count(monitor: Any) -> int:
    return monitor.get_supervision_snapshot()["cam"]["restart_count"]


def _config_reasons(pm: Any) -> list[dict]:
    _ready, reasons = pm._evaluate_run_readiness()
    return [r for r in reasons if r["source"] == "config"]


# --------------------------------------------------------------------------- #
# Вход 1: негодное поле (max_retries: "abc") — флаг не активен + config-причина, супервизор не поднимает
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_bad_max_retries_pm_and_monitor_agree() -> None:
    """``max_retries: "abc"`` при ``enabled`` и ``run_auto_restart``: схема отвергает dict. PM: флаг не действует,
    причина ``failure`` / ``config`` «restart_policy негоден: cam», система не готова. Супервизор: упавший процесс не
    перезапускается (``restart_count`` 0). До правки PM считал флаг активным (``enabled is True``): причины конфига нет,
    в ``running`` он 30 с держал ``out_of_spec`` «перезапуск cam», хотя никто не перезапускает."""
    pm, monitor = _pm_with({"enabled": True, "run_auto_restart": True, "max_retries": "abc", "backoff_sec": _BACKOFF})

    ready, reasons = pm._evaluate_run_readiness()
    assert ready is False
    assert [(r["node"], r["severity"], r["source"], r["reason"]) for r in reasons] == [
        ("cam", "failure", "config", _CONFIG_REASON_TEXT)
    ], reasons

    _crash_and_tick(pm, monitor)
    assert _restart_count(monitor) == 0, monitor.get_supervision_snapshot()


# --------------------------------------------------------------------------- #
# Вход 2-3: enabled: 1 / "true" — схема приводит к True; PM и монитор согласны: флаг активен, ложной ошибки нет
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("enabled", [1, "true"], ids=["int-1", "str-true"])
def test_enabled_truthy_non_bool_pm_and_monitor_agree(enabled: Any) -> None:
    """Схема (pydantic, lax) приводит ``enabled: 1`` и ``"true"`` к ``True``, поэтому супервизор такой процесс
    перезапускает. PM согласен: флаг активен, config-причин нет (ложной ошибки «требует enabled: true» нет), система
    готова; в ``running`` упавший процесс -> одна ``out_of_spec`` «перезапуск cam», монитор запланировал рестарт."""
    pm, monitor = _pm_with({"enabled": enabled, "run_auto_restart": True, "backoff_sec": _BACKOFF})

    assert _config_reasons(pm) == []
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}

    _crash_and_tick(pm, monitor)

    assert _restart_count(monitor) == 1, monitor.get_supervision_snapshot()
    status = pm._cmd_system_run_status()
    assert status["state"] == "running", status
    assert [(r["node"], r["severity"], r["source"], r["reason"]) for r in status["reasons"]] == [
        ("cam", "out_of_spec", "liveness", "перезапуск cam")
    ], status


# --------------------------------------------------------------------------- #
# Негодный per-process dict: причина без значений входа
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "bad",
    [
        {"enabled": True, "run_auto_restart": True, "max_retries": "SECRET-abc"},
        {"enabled": True, "backoff_mode": "SECRET-exponentail"},
    ],
    ids=["bad-int-field", "bad-literal-typo"],
)
def test_invalid_per_process_dict_gives_config_reason_without_values(bad: dict) -> None:
    """Негодный ``restart_policy`` процесса -> ровно одна причина ``failure`` / ``config`` «restart_policy негоден:
    cam»; значение входа (``SECRET-...``) ни в причине, ни в тексте ответа ``system.run.status`` не появляется."""
    pm, _monitor = _pm_with(bad)

    config = _config_reasons(pm)
    assert config == [{"node": "cam", "severity": "failure", "reason": _CONFIG_REASON_TEXT, "source": "config"}]
    assert "SECRET" not in json.dumps(pm._cmd_system_run_status(), ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Охрана: валидный dict — прежние причины; публичный разбор монитора
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_valid_flag_without_enabled_keeps_old_reason_not_invalid_one() -> None:
    """Схема валидна, флаг включён, ``enabled`` выключен -> прежняя причина «требует enabled: true», НЕ «негоден»."""
    pm, _monitor = _pm_with({"run_auto_restart": True})

    config = _config_reasons(pm)
    assert [r["reason"].replace("`", "") for r in config] == ["cam: run_auto_restart требует enabled: true"]


@pytest.mark.timeout(60)
def test_monitor_resolve_policy_reports_validity() -> None:
    """Публичный ``resolve_policy``: годный dict -> (его политика, True); негодный -> (глобальная, False);
    dict нет -> (глобальная, True)."""
    pm, monitor = make_readiness_pm(
        {
            "good": {"class": "X", "restart_policy": {"enabled": True, "max_retries": 7}},
            "bad": {"class": "X", "restart_policy": {"max_retries": "abc"}},
            "none": {"class": "X"},
        }
    )

    good, good_ok = monitor.resolve_policy("good")
    assert (good_ok, good.enabled, good.max_retries) == (True, True, 7)

    bad, bad_ok = monitor.resolve_policy("bad")
    assert (bad_ok, bad is monitor.restart_policy) == (False, True)

    none, none_ok = monitor.resolve_policy("none")
    assert (none_ok, none is monitor.restart_policy) == (True, True)
    assert isinstance(good, RestartPolicy)
