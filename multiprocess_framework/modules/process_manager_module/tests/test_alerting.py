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

    def test_paths_for_substitutes_process(self) -> None:
        rule = AlertRule("r", counter_paths=("processes.{process}.state.drops",))
        assert rule.paths_for("cam") == ["processes.cam.state.drops"]

    def test_paths_for_empty_when_event_rule(self) -> None:
        assert AlertRule("r", events=("crashed",)).paths_for("cam") == []

    def test_default_drops_rule_uses_real_published_field(self) -> None:
        """Регресс-страж находки ревью: путь обязан совпадать с реальным публикатором.

        Живой публикатор — capture-плагин: merge в ``processes.<name>.state`` с полем
        ``drops``. Дефолт, указывающий на непубликуемое имя, делает правило молча
        мёртвым (алерт «дропы растут» не сработает никогда).
        """
        rule = next(r for r in DEFAULT_RULES if r.name == "drops_growing")
        assert "processes.{process}.state.drops" in rule.counter_paths
        # первым кандидатом идёт реально публикуемое имя
        assert rule.counter_paths[0].endswith(".state.drops")


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

    def test_bool_is_not_counter(self) -> None:
        # bool — подкласс int: True не должен становиться «счётчиком 1»
        assert counter_growth(False, True) == 0
        assert counter_growth(0, True) == 0


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
    _PATH = "processes.cam.state.drops"

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


class TestAlertHardening:
    """Находки Fable-ревью NEW-7: fallback путей, сброс на switch, cooldown счётчика."""

    def test_falls_back_to_second_candidate_path(self) -> None:
        """Первый путь не резолвится → берём следующий кандидат (правило не умирает)."""
        alt = "processes.cam.state.drops_count"
        _pm, mon, store, published = _monitor({alt: 3}, procs=["cam"])
        mon._check_counter_alerts()  # база по второму кандидату
        assert mon._counter_baseline[("drops_growing", "cam")] == 3
        store[alt] = 7
        mon._check_counter_alerts()
        assert [v for p, v in published if p.endswith("drops_growing.severity")] == ["warning"]

    def test_forget_process_resets_cooldown(self) -> None:
        """MED-1: cooldown СТАРОГО инстанса не должен глушить алерт нового имени."""
        _pm, mon, _store, published = _monitor()
        mon._emit_supervisor_event("cam", "gave_up", reason="старый инстанс")
        mon.forget_process("cam")  # switch/hot-swap
        mon._emit_supervisor_event("cam", "gave_up", reason="новый инстанс")

        sev = [p for p, _ in published if p.endswith("supervisor_gave_up.severity")]
        assert len(sev) == 2, "второй critical подавлен чужим cooldown'ом"

    def test_forget_process_clears_alert_state(self) -> None:
        _pm, mon, _store, _published = _monitor({"processes.cam.state.drops": 1}, procs=["cam"])
        mon._check_counter_alerts()
        mon._emit_supervisor_event("cam", "gave_up", reason="x")
        mon.forget_process("cam")
        assert not [k for k in mon._alert_last_fired if k[1] == "cam"]
        assert not [k for k in mon._counter_baseline if k[1] == "cam"]

    def test_forget_process_deletes_alerts_subtree(self) -> None:
        """MED-2: имя ушло из топологии → его алерты не остаются в дереве навсегда."""
        deleted: list[str] = []
        pm = MagicMock()
        pm._process_configs = {}

        class _SSM:
            def handle_state_get(self, msg):
                return {"status": "error"}

            def handle_state_delete(self, msg):
                deleted.append(msg["data"]["path"])
                return {"status": "ok"}

        pm._state_store_manager = _SSM()
        mon = ProcessMonitor(pm, restart_policy=RestartPolicy(enabled=True))
        mon.forget_process("cam")
        assert "system.alerts.cam" in deleted

    def test_counter_alert_respects_cooldown(self) -> None:
        """Непрерывный рост в окне cooldown даёт ОДИН алерт, а не поток."""
        _pm, mon, store, published = _monitor({"processes.cam.state.drops": 0}, procs=["cam"])
        mon._check_counter_alerts()  # база
        for i in range(1, 6):
            store["processes.cam.state.drops"] = i
            mon._check_counter_alerts()
        assert len([p for p, _ in published if p.endswith("drops_growing.severity")]) == 1

    def test_min_growth_threshold(self) -> None:
        """min_growth > 1: прирост ниже порога алерт не поднимает."""
        from ..core.alert_rules import AlertRule

        _pm, mon, store, published = _monitor({"processes.cam.state.drops": 0}, procs=["cam"])
        mon._alert_rules = (AlertRule("big_drops", counter_paths=("processes.{process}.state.drops",), min_growth=5),)
        mon._check_counter_alerts()  # база
        store["processes.cam.state.drops"] = 3  # ниже порога
        mon._check_counter_alerts()
        assert not any("big_drops" in p for p, _ in published)

        store["processes.cam.state.drops"] = 20  # прирост 17 ≥ 5
        mon._check_counter_alerts()
        assert any("big_drops.severity" in p for p, _ in published)
