# -*- coding: utf-8 -*-
"""fix-B3 / F1 (свежее ревью Ф1 run-state): форма листа готовности проверяется на ВХОДЕ heartbeat.

Раньше монитор клал в ``_readiness`` любой dict, а ``evaluate`` на одном листе с ``reasons = 5`` бросал: такт терялся
целиком (ERROR на каждом такте), и авария соседа не обнаруживалась — система оставалась в ``running``.

Теперь ``_admit_heartbeat`` нормализует лист (одна функция ``normalize_leaf``): негодная форма не принимается как лист
готовности — у ЭТОГО процесса вместо неё лист ``ready: false`` с одной причиной ``failure`` / ``report`` «лист
готовности негоден: <процесс>» (значений входа в причине нет). Сам heartbeat остаётся фактом жизни: время и статус
(``paused`` / ``running``) принимаются. Остальные процессы и их аварии обрабатываются как обычно.

Обвязка — настоящие ``ProcessManagerProcess`` + ``ProcessMonitor`` (``make_readiness_pm``). Ожидания — литералы.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from .test_run_commands import beat, make_readiness_pm

_INVALID = {"node": "a", "severity": "failure", "reason": "лист готовности негоден: a", "source": "report"}


def _leaf(**fields: Any) -> dict:
    base: dict[str, Any] = {"ready": True, "reasons": [], "paused": False, "at": time.time()}
    base.update(fields)
    return base


def _send(monitor: Any, name: str, readiness: Any, **extra: Any) -> None:
    monitor._on_heartbeat_received({"sender": name, "timestamp": time.time(), "readiness": readiness, **extra})


def _raw_tick(monitor: Any) -> None:
    """Такт монитора без проверки «нет ошибок» (до правки такт готовности писал ERROR — это и есть дефект)."""
    with monitor._iteration_lock:
        monitor._run_iteration()


def _running_pm() -> tuple[Any, Any]:
    pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}, "b": {"class": "pkg.B"}})
    beat(monitor, "a")
    beat(monitor, "b")
    _raw_tick(monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    return pm, monitor


# --------------------------------------------------------------------------- #
# R1 ревью: битый лист одного процесса не выключает обнаружение аварии соседа
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_bad_leaf_of_one_process_does_not_blind_crash_detection_of_another() -> None:
    """``running`` (a, b); ``a`` присылает ``reasons = 5``; затем ``b`` падает; три такта. До правки каждый такт
    бросал ``'int' object is not iterable`` и состояние оставалось ``running``. Теперь — ``fault``, причины: негодный
    лист ``a`` и «процесс не жив» у ``b``; сбоев такта готовности в журнале нет."""
    pm, monitor = _running_pm()

    _send(monitor, "a", _leaf(reasons=5))
    proc_b = pm._process_registry.get_process_by_name("b")
    proc_b._alive = False
    proc_b.exitcode = -9
    pm._log_error.reset_mock()
    for _ in range(3):
        _raw_tick(monitor)

    assert pm._run_state == "fault", pm._run_state
    status = pm._cmd_system_run_status()
    assert [(r["node"], r["severity"], r["reason"]) for r in status["reasons"]] == [
        ("a", "failure", "лист готовности негоден: a"),
        ("b", "failure", "процесс не жив"),
    ], status
    tick_errors = [c.args[0] for c in pm._log_error.call_args_list if c.args and "readiness tick" in c.args[0]]
    assert tick_errors == [], tick_errors  # падение ``b`` монитор журналирует сам — это не сбой такта готовности


# --------------------------------------------------------------------------- #
# Формы: каждая негодная даёт одну и ту же причину, без значений входа
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"reasons": 5}, id="reasons-int"),
        pytest.param({"reasons": "SECRET"}, id="reasons-str"),
        pytest.param({"reasons": None}, id="reasons-none"),
        pytest.param({"reasons": [1]}, id="reason-item-int"),
        pytest.param({"reasons": ["SECRET"]}, id="reason-item-str"),
        pytest.param({"ready": "SECRET"}, id="ready-str"),
        pytest.param({"ready": 1}, id="ready-int"),
        pytest.param({"paused": "SECRET"}, id="paused-str"),
        pytest.param({"at": "SECRET"}, id="at-str"),
        pytest.param({"at": None}, id="at-none"),
        pytest.param({"at": float("nan")}, id="at-nan"),
        pytest.param({"at": float("inf")}, id="at-inf"),
        pytest.param({"at": True}, id="at-bool"),
        pytest.param("SECRET", id="whole-leaf-str"),
        pytest.param(5, id="whole-leaf-int"),
    ],
)
def test_bad_leaf_form_replaced_by_one_failure_without_input_values(bad: Any) -> None:
    """Негодная форма -> лист процесса: ``ready: false``, одна причина «лист готовности негоден: a» (``failure`` /
    ``report``); значение входа (``SECRET``) в листе не остаётся."""
    _pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}})

    _send(monitor, "a", _leaf(**bad) if isinstance(bad, dict) else bad)

    leaf = monitor.readiness_snapshot()["a"]
    assert (leaf["ready"], leaf["reasons"]) == (False, [_INVALID]), leaf
    assert "SECRET" not in json.dumps(leaf, ensure_ascii=False)


@pytest.mark.timeout(60)
def test_bad_leaf_packet_still_counts_as_life_and_status() -> None:
    """Битый лист — не потеря heartbeat: процесс жив. Время heartbeat принято, статус ``paused`` из того же пакета
    применён; лист — негодный."""
    _pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}})

    _send(monitor, "a", _leaf(reasons=5), status="paused")

    assert monitor.get_stats()["last_heartbeats"]["a"] < 5.0
    assert monitor.previous_states["a"]["status"] == "paused"
    assert monitor.readiness_snapshot()["a"]["reasons"] == [_INVALID]


@pytest.mark.timeout(60)
def test_good_leaf_is_stored_as_sent() -> None:
    """Охрана: годный лист (с реальными причинами, ``paused: true``) принимается без изменений."""
    _pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}})
    sent = _leaf(
        ready=False,
        paused=True,
        reasons=[{"node": "a.p", "severity": "failure", "reason": "модель не загружена", "source": "readiness"}],
    )

    _send(monitor, "a", dict(sent))

    assert monitor.readiness_snapshot()["a"] == sent


@pytest.mark.timeout(60)
def test_bad_leaf_is_replaced_by_the_next_good_one() -> None:
    """Негодный лист не «залипает»: следующий годный heartbeat возвращает процессу его настоящий лист."""
    _pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}})

    _send(monitor, "a", _leaf(reasons=5))
    good = _leaf()
    _send(monitor, "a", dict(good))

    assert monitor.readiness_snapshot()["a"] == good
