# -*- coding: utf-8 -*-
"""Тесты OTP-стратегий супервизии (NEW-6b): rest_for_one / one_for_all + группы.

Три уровня:
  1. ``_resolve_restart_set`` / ``_topo_order`` — чистые функции (кого рестартить).
  2. ``_cascade_restart`` через ``_try_auto_restart`` — induced-рестарты в
     ``_pending_restarts``, БЕЗ метки в ``_restart_history`` члена (интенсивность —
     свойство супервизора, семантика OTP).
  3. Проброс ``supervision_group`` от ``ProcessConfig`` до верхнего уровня ``proc_dict``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ..core.restart_policy import RestartPolicy
from ..monitor.process_monitor import ProcessMonitor
from ..topology.blueprint import ProcessConfig

_rs = ProcessMonitor._resolve_restart_set

# cam → seg → lines (группа vision); pult — отдельная группа ctl
_GROUPS = {"cam": "vision", "seg": "vision", "lines": "vision", "pult": "ctl"}
_DEPS = {"cam": [], "seg": ["cam"], "lines": ["seg"], "pult": []}


class TestResolveRestartSet:
    def test_one_for_one_is_empty(self) -> None:
        assert _rs("cam", "one_for_one", _GROUPS, _DEPS) == []

    def test_rest_for_one_transitive_downstream(self) -> None:
        assert _rs("cam", "rest_for_one", _GROUPS, _DEPS) == ["seg", "lines"]

    def test_rest_for_one_from_middle(self) -> None:
        assert _rs("seg", "rest_for_one", _GROUPS, _DEPS) == ["lines"]

    def test_rest_for_one_leaf_has_no_dependents(self) -> None:
        assert _rs("lines", "rest_for_one", _GROUPS, _DEPS) == []

    def test_rest_for_one_never_includes_failed(self) -> None:
        assert "cam" not in _rs("cam", "rest_for_one", _GROUPS, _DEPS)

    def test_rest_for_one_restricted_to_group(self) -> None:
        # 'ext' зависит от cam, но в другой группе → каскад его не трогает
        groups = {**_GROUPS, "ext": "other"}
        deps = {**_DEPS, "ext": ["cam"]}
        assert _rs("cam", "rest_for_one", groups, deps) == ["seg", "lines"]

    def test_rest_for_one_without_group_uses_whole_graph(self) -> None:
        groups = {n: "" for n in _DEPS}
        assert _rs("cam", "rest_for_one", groups, _DEPS) == ["seg", "lines"]

    def test_one_for_all_group_members_except_failed(self) -> None:
        assert _rs("cam", "one_for_all", _GROUPS, _DEPS) == ["seg", "lines"]
        assert _rs("lines", "one_for_all", _GROUPS, _DEPS) == ["cam", "seg"]

    def test_one_for_all_excludes_other_groups(self) -> None:
        assert "pult" not in _rs("cam", "one_for_all", _GROUPS, _DEPS)

    def test_one_for_all_without_group_is_empty(self) -> None:
        assert _rs("x", "one_for_all", {"x": ""}, {"x": []}) == []

    def test_unknown_strategy_is_empty(self) -> None:
        assert _rs("cam", "bogus", _GROUPS, _DEPS) == []


class TestTopoOrder:
    def test_upstream_before_dependent(self) -> None:
        assert ProcessMonitor._topo_order(["lines", "seg", "cam"], _DEPS) == ["cam", "seg", "lines"]

    def test_external_deps_ignored(self) -> None:
        # 'seg' зависит от 'cam', которого нет в списке → ребро не мешает
        assert ProcessMonitor._topo_order(["seg", "lines"], _DEPS) == ["seg", "lines"]

    def test_cycle_does_not_hang(self) -> None:
        out = ProcessMonitor._topo_order(["a", "b"], {"a": ["b"], "b": ["a"]})
        assert sorted(out) == ["a", "b"]


# ── Уровень 2: каскад через монитор ──────────────────────────────────────────


def _make_pm(configs: dict) -> MagicMock:
    pm = MagicMock()
    pm.name = "ProcessManager"
    pm._get_protected_names.return_value = set()
    pm.communication.send_message.return_value = True
    pm._process_configs = configs
    pm.shared_resources = None
    return pm


def _configs(groups: dict[str, str], deps: dict[str, list[str]]) -> dict:
    return {
        n: {"class": "pkg.M", "supervision_group": groups.get(n, ""), "depends_on": deps.get(n, [])}
        for n in set(groups) | set(deps)
    }


@pytest.fixture
def monitor_factory():
    def _make(strategy: str, **policy_kw):
        pm = _make_pm(_configs(_GROUPS, _DEPS))
        pol = RestartPolicy(enabled=True, backoff_sec=0.0, strategy=strategy, **policy_kw)
        return pm, ProcessMonitor(pm, restart_policy=pol)

    return _make


class TestCascadeIntegration:
    def test_one_for_one_no_cascade(self, monitor_factory) -> None:
        _pm, mon = monitor_factory("one_for_one")
        mon._try_auto_restart("cam", reason="crashed")
        assert set(mon._pending_restarts) == {"cam"}

    def test_rest_for_one_schedules_downstream(self, monitor_factory) -> None:
        _pm, mon = monitor_factory("rest_for_one")
        mon._try_auto_restart("cam", reason="crashed")
        assert set(mon._pending_restarts) == {"cam", "seg", "lines"}
        assert "pult" not in mon._pending_restarts

    def test_one_for_all_schedules_group(self, monitor_factory) -> None:
        _pm, mon = monitor_factory("one_for_all")
        mon._try_auto_restart("seg", reason="crashed")
        assert set(mon._pending_restarts) == {"cam", "seg", "lines"}

    def test_induced_does_not_charge_history(self, monitor_factory) -> None:
        """Метка идёт ТОЛЬКО триггеру: give-up не должен наступать у здоровых членов."""
        _pm, mon = monitor_factory("rest_for_one")
        mon._try_auto_restart("cam", reason="crashed")
        assert len(mon._restart_history.get("cam", [])) == 1
        assert mon._restart_history.get("seg", []) == []
        assert mon._restart_history.get("lines", []) == []

    def test_induced_marks_pending_recovery_and_deadline(self, monitor_factory) -> None:
        _pm, mon = monitor_factory("rest_for_one")
        mon._try_auto_restart("cam", reason="crashed")
        for n in ("cam", "seg", "lines"):
            assert n in mon._pending_recovery
            assert n in mon._recovery_deadline

    def test_cascade_skips_protected(self, monitor_factory) -> None:
        pm, mon = monitor_factory("rest_for_one")
        pm._get_protected_names.return_value = {"lines"}
        mon._try_auto_restart("cam", reason="crashed")
        assert "lines" not in mon._pending_restarts
        assert "seg" in mon._pending_restarts

    def test_cascade_skips_given_up(self, monitor_factory) -> None:
        _pm, mon = monitor_factory("rest_for_one")
        mon._given_up.add("lines")  # терминальное состояние — не воскрешаем каскадом
        mon._try_auto_restart("cam", reason="crashed")
        assert "lines" not in mon._pending_restarts

    def test_cascade_does_not_override_existing_pending(self, monitor_factory) -> None:
        _pm, mon = monitor_factory("rest_for_one")
        mon._pending_restarts["seg"] = 12345.0
        mon._try_auto_restart("cam", reason="crashed")
        assert mon._pending_restarts["seg"] == 12345.0  # свой план не затёрт

    def test_one_for_all_without_group_warns_and_degrades(self) -> None:
        pm = _make_pm(_configs({"solo": ""}, {"solo": []}))
        pol = RestartPolicy(enabled=True, backoff_sec=0.0, strategy="one_for_all")
        mon = ProcessMonitor(pm, restart_policy=pol)
        mon._try_auto_restart("solo", reason="crashed")
        assert set(mon._pending_restarts) == {"solo"}
        assert pm._log_warning.called

    def test_disabled_policy_no_cascade(self) -> None:
        pm = _make_pm(_configs(_GROUPS, _DEPS))
        pol = RestartPolicy(enabled=False, strategy="one_for_all")
        mon = ProcessMonitor(pm, restart_policy=pol)
        mon._try_auto_restart("cam", reason="crashed")
        assert mon._pending_restarts == {}


class TestGroupGiveupEscalation:
    """NEW-6b: супервизор сдался по триггеру → члены группы помечены деградировавшими."""

    def _exhaust(self, mon, name: str, times: int) -> None:
        for _ in range(times):
            mon._try_auto_restart(name, reason="crashed")
            mon._pending_restarts.clear()
            mon._pending_recovery.clear()

    def test_escalation_marks_group_members(self, monitor_factory) -> None:
        pm, mon = monitor_factory("rest_for_one", max_retries=2, window_sec=0.0)
        published: list[tuple[str, object]] = []
        mon._publish_state = lambda p, v: published.append((p, v))  # type: ignore[assignment]

        self._exhaust(mon, "cam", 2)
        mon._try_auto_restart("cam", reason="crashed")  # 3-я → give-up

        assert mon.previous_states["cam"]["status"] == "failed"
        paths = [p for p, _ in published]
        assert any("seg" in p and "degraded_reason" in p for p in paths)
        assert any("lines" in p and "degraded_reason" in p for p in paths)
        assert pm._log_error.called

    def test_no_escalation_for_one_for_one(self, monitor_factory) -> None:
        pm, mon = monitor_factory("one_for_one", max_retries=1, window_sec=0.0)
        published: list[tuple[str, object]] = []
        mon._publish_state = lambda p, v: published.append((p, v))  # type: ignore[assignment]

        self._exhaust(mon, "cam", 1)
        mon._try_auto_restart("cam", reason="crashed")

        assert not any("seg" in p for p, _ in published)

    def test_escalation_skips_already_given_up(self, monitor_factory) -> None:
        _pm, mon = monitor_factory("rest_for_one", max_retries=1, window_sec=0.0)
        mon._given_up.add("seg")
        published: list[tuple[str, object]] = []
        mon._publish_state = lambda p, v: published.append((p, v))  # type: ignore[assignment]

        self._exhaust(mon, "cam", 1)
        mon._try_auto_restart("cam", reason="crashed")

        assert not any("seg" in p and "degraded_reason" in p for p, _ in published)
        assert any("lines" in p and "degraded_reason" in p for p, _ in published)


# ── Уровень 3: проброс supervision_group ─────────────────────────────────────


class TestGroupThreading:
    def test_group_reaches_proc_dict(self) -> None:
        pc = ProcessConfig(process_name="seg", supervision_group="vision")
        _name, proc_dict = pc.as_generic_config().build()
        assert proc_dict.get("supervision_group") == "vision"

    def test_empty_group_absent_from_proc_dict(self) -> None:
        pc = ProcessConfig(process_name="seg")
        _name, proc_dict = pc.as_generic_config().build()
        assert "supervision_group" not in proc_dict

    def test_default_strategy_is_one_for_one(self) -> None:
        assert RestartPolicy().strategy == "one_for_one"

    def test_invalid_strategy_raises(self) -> None:
        with pytest.raises(Exception):
            RestartPolicy(strategy="rest_for_two")
