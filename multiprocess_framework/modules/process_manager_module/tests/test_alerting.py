# -*- coding: utf-8 -*-
"""Тесты алертинга поверх supervisor-событий и счётчиков (NEW-7).

Два уровня:
  1. ``core/alert_rules.py`` — чистые функции (выборка правил, антидребезг, прирост).
  2. Интеграция в ``ProcessMonitor``: событийные алерты из ``_emit_supervisor_event``,
     счётчиковые из ``_check_counter_alerts``, флаг ``FW_SUPERVISOR_ALERTS``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ..core.alert_rules import (
    DEFAULT_RULES,
    AlertRule,
    counter_growth,
    counter_rules,
    rules_for_event,
    should_fire,
)
from ..core.restart_policy import RestartPolicy
from ..monitor.process_monitor import ProcessMonitor


class TestRuleSelection:
    def test_rules_for_event_matches_gave_up(self) -> None:
        got = rules_for_event(DEFAULT_RULES, "gave_up")
        assert [r.name for r in got] == ["supervisor_gave_up"]
        assert got[0].severity == "critical"

    def test_rules_for_event_unknown_is_empty(self) -> None:
        assert rules_for_event(DEFAULT_RULES, "recovered") == []

    def test_counter_rules_only_with_path(self) -> None:
        got = counter_rules(DEFAULT_RULES)
        assert [r.name for r in got] == ["drops_growing"]

    def test_path_for_substitutes_process(self) -> None:
        rule = AlertRule("r", counter_path="processes.{process}.state.drops_count")
        assert rule.path_for("cam") == "processes.cam.state.drops_count"

    def test_path_for_empty_when_event_rule(self) -> None:
        assert AlertRule("r", events=("crashed",)).path_for("cam") == ""


class TestShouldFire:
    def test_first_time_fires(self) -> None:
        assert should_fire(None, now=100.0, cooldown_sec=60.0) is True

    def test_within_cooldown_suppressed(self) -> None:
        assert should_fire(100.0, now=130.0, cooldown_sec=60.0) is False

    def test_after_cooldown_fires(self) -> None:
        assert should_fire(100.0, now=161.0, cooldown_sec=60.0) is True

    def test_zero_cooldown_always_fires(self) -> None:
        assert should_fire(100.0, now=100.1, cooldown_sec=0.0) is True


class TestCounterGrowth:
    def test_positive_delta(self) -> None:
        assert counter_growth(10, 13) == 3

    def test_no_change(self) -> None:
        assert counter_growth(10, 10) == 0

    def test_reset_is_not_growth(self) -> None:
        # процесс перезапущен → счётчик обнулился; это не всплеск потерь
        assert counter_growth(10, 0) == 0

    def test_non_int_is_zero(self) -> None:
        assert counter_growth(None, 5) == 0
        assert counter_growth(5, None) == 0
        assert counter_growth(5, "7") == 0


# ── Интеграция в монитор ─────────────────────────────────────────────────────


def _monitor(state: dict | None = None, procs: list[str] | None = None):
    """Монитор с фейковым StateStore (state-словарь) и списком процессов."""
    pm = MagicMock()
    pm.name = "ProcessManager"
    pm._get_protected_names.return_value = set()
    pm._process_configs = {}

    store = dict(state or {})

    class _SSM:
        def handle_state_get(self, msg):
            path = msg["data"]["path"]
            return {"status": "ok", "value": store[path]} if path in store else {"status": "error"}

    pm._state_store_manager = _SSM()
    mon = ProcessMonitor(pm, restart_policy=RestartPolicy(enabled=True))
    if procs is not None:
        os_procs = []
        for n in procs:
            p = MagicMock()
            p.name = n
            os_procs.append(p)
        pm._process_registry.os_processes = os_procs
    published: list[tuple[str, object]] = []
    mon._publish_state = lambda p, v: published.append((p, v))  # type: ignore[assignment]
    return pm, mon, store, published


class TestEventAlerts:
    def test_gave_up_raises_critical_alert(self) -> None:
        pm, mon, _store, published = _monitor()
        mon._emit_supervisor_event("cam", "gave_up", reason="3 рестарта", level="error")

        sev = [v for p, v in published if p.endswith("supervisor_gave_up.severity")]
        assert sev == ["critical"]
        assert any("[alert:critical]" in str(c) for c in pm._log_error.call_args_list)

    def test_unresponsive_raises_warning(self) -> None:
        _pm, mon, _store, published = _monitor()
        mon._emit_supervisor_event("cam", "unresponsive", reason="нет heartbeat")

        sev = [v for p, v in published if p.endswith("process_unresponsive.severity")]
        assert sev == ["warning"]

    def test_recovered_raises_nothing(self) -> None:
        _pm, mon, _store, published = _monitor()
        mon._emit_supervisor_event("cam", "recovered", level="info")
        assert not any("system.alerts" in p for p, _ in published)

    def test_cooldown_dedups_repeat(self) -> None:
        _pm, mon, _store, published = _monitor()
        mon._emit_supervisor_event("cam", "gave_up", reason="раз")
        mon._emit_supervisor_event("cam", "gave_up", reason="два")
        assert len([p for p, _ in published if p.endswith("supervisor_gave_up.severity")]) == 1

    def test_alerts_are_per_process(self) -> None:
        _pm, mon, _store, published = _monitor()
        mon._emit_supervisor_event("cam", "gave_up", reason="a")
        mon._emit_supervisor_event("seg", "gave_up", reason="b")
        paths = [p for p, _ in published if p.endswith(".severity")]
        assert any("alerts.cam." in p for p in paths)
        assert any("alerts.seg." in p for p in paths)

    def test_flag_off_disables_alerts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FW_SUPERVISOR_ALERTS", "0")
        _pm, mon, _store, published = _monitor()
        mon._emit_supervisor_event("cam", "gave_up", reason="x")
        assert not any("system.alerts" in p for p, _ in published)


class TestCounterAlerts:
    _PATH = "processes.cam.state.drops_count"

    def test_first_pass_only_baselines(self) -> None:
        _pm, mon, _store, published = _monitor({self._PATH: 5}, procs=["cam"])
        mon._check_counter_alerts()
        assert not any("system.alerts" in p for p, _ in published)
        assert mon._counter_baseline[("drops_growing", "cam")] == 5

    def test_growth_fires_alert(self) -> None:
        _pm, mon, store, published = _monitor({self._PATH: 5}, procs=["cam"])
        mon._check_counter_alerts()  # база
        store[self._PATH] = 9
        mon._check_counter_alerts()

        sev = [v for p, v in published if p.endswith("drops_growing.severity")]
        assert sev == ["warning"]
        reasons = [v for p, v in published if p.endswith("drops_growing.reason")]
        assert "вырос на 4" in str(reasons[0])

    def test_no_growth_no_alert(self) -> None:
        _pm, mon, _store, published = _monitor({self._PATH: 5}, procs=["cam"])
        mon._check_counter_alerts()
        mon._check_counter_alerts()
        assert not any("system.alerts" in p for p, _ in published)

    def test_counter_reset_no_alert(self) -> None:
        _pm, mon, store, published = _monitor({self._PATH: 5}, procs=["cam"])
        mon._check_counter_alerts()
        store[self._PATH] = 0  # рестарт процесса обнулил счётчик
        mon._check_counter_alerts()
        assert not any("system.alerts" in p for p, _ in published)
        assert mon._counter_baseline[("drops_growing", "cam")] == 0

    def test_missing_path_is_silent(self) -> None:
        _pm, mon, _store, published = _monitor({}, procs=["cam"])
        mon._check_counter_alerts()
        assert published == []

    def test_no_state_store_degrades(self) -> None:
        pm = MagicMock()
        pm._state_store_manager = None
        mon = ProcessMonitor(pm, restart_policy=RestartPolicy(enabled=True))
        assert mon._read_state_int("any.path") is None

    def test_bool_is_not_counter(self) -> None:
        _pm, mon, _store, _published = _monitor({self._PATH: True}, procs=["cam"])
        assert mon._read_state_int(self._PATH) is None
