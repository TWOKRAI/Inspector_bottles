# -*- coding: utf-8 -*-
"""Task 1.5 (system-run-state) — hazard-тесты автора гейта ``topology.apply``: порядок, ``run_gate: false``, гонки.

Обвязка и литералы — из слепого ``test_run_apply_gate.py`` (``_pm_in``, ``_APPLY_ARGS``, ``_bounded``). Зависающее —
в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import copy
import threading
from unittest.mock import MagicMock

import pytest

from ..process.process_manager_process import ProcessManagerProcess
from .conftest import wire_planner
from .test_run_apply_gate import _APPLY_ARGS, _bounded, _pm_in
from .test_run_commands import make_readiness_pm

_REFUSAL_CODES = {"running", "stopping", "fault_unacknowledged", "shutting_down"}


def _args() -> dict:
    return copy.deepcopy(_APPLY_ARGS)


@pytest.mark.timeout(60)
@pytest.mark.parametrize("state", ["running", "stopping", "fault", "shutting_down"])
def test_gate_is_before_debounce_retarget_and_apply_topology(state: str) -> None:
    """Отказ — раньше debounce, ретаргета адреса рецепта и ``apply_topology``; флаги debounce не тронуты."""
    pm = _pm_in(state)
    pm._topology_debounce_reject = MagicMock(return_value=None)
    pm._retarget_recipe_address = MagicMock()
    pm._observability_recipe_address = MagicMock(return_value="")
    pm.apply_topology = MagicMock(return_value={"success": True})
    last_ts = pm._last_replace_ts

    reply = _bounded(lambda: pm._cmd_topology_apply(_args()))

    assert reply["success"] is False and reply["error"] in _REFUSAL_CODES, reply
    pm._topology_debounce_reject.assert_not_called()
    pm._retarget_recipe_address.assert_not_called()
    pm.apply_topology.assert_not_called()
    assert pm._replace_in_progress is False and pm._last_replace_ts == last_ts


@pytest.mark.timeout(60)
def test_gate_also_with_run_gate_false() -> None:
    """``run_gate: false``: машина ведётся всегда — apply в ``running`` отказан так же; событие не тронуто."""
    pm, _monitor = make_readiness_pm({"w1": {"class": "m.W1"}}, run_gate=False)
    pm._setup_topology_manager()
    wire_planner(pm)
    pm._ensure_routing_state()
    assert pm._run_apply("start", ready=True)[0].value == "running"
    assert pm._run_event.is_set() is True
    pm._topology_debounce_reject = MagicMock(return_value=None)

    reply = _bounded(lambda: pm._cmd_topology_apply(_args()))

    assert reply == {"success": False, "error": "running", "message": "сначала ОСТАНОВИТЬ"}, reply
    pm._topology_debounce_reject.assert_not_called()  # гейт раньше debounce и при run_gate: false
    assert pm._run_snapshot()[0].value == "running"
    assert pm._run_event.is_set() is True
    assert set(pm._process_configs) == {"w1"}


@pytest.mark.timeout(60)
def test_gate_comes_before_missing_topology_dict_check() -> None:
    """Без ``topology_dict``: в ``running`` отказывает гейт (он первый), в ``ready`` — прежняя проверка аргумента."""
    running = _pm_in("running")
    assert _bounded(lambda: running._cmd_topology_apply({}))["error"] == "running"

    ready = _pm_in("ready")
    assert _bounded(lambda: ready._cmd_topology_apply({})) == {"error": "topology_dict required"}


@pytest.mark.timeout(60)
def test_state_changed_between_gate_and_transition_is_refused_without_side_effects() -> None:
    """START успел между гейтом и переходом ``apply`` (подменой debounce): отказ ``running``, ретаргета нет."""
    pm = _pm_in("ready")
    pm._retarget_recipe_address = MagicMock()
    pm.apply_topology = MagicMock(return_value={"success": True})

    def start_in_between() -> None:
        assert pm._run_apply("start", ready=True)[2].value == "ready"
        return None

    pm._topology_debounce_reject = start_in_between

    reply = _bounded(lambda: pm._cmd_topology_apply(_args()))

    assert reply == {"success": False, "error": "running", "message": "сначала ОСТАНОВИТЬ"}, reply
    pm._retarget_recipe_address.assert_not_called()
    pm.apply_topology.assert_not_called()
    assert pm._run_snapshot()[0].value == "running"
    assert pm._run_event.is_set() is True


@pytest.mark.timeout(60)
@pytest.mark.parametrize("before", ["booting", "ready"])
def test_repeated_apply_not_blocked_and_settles(before: str) -> None:
    """``booting`` (прежний apply не закрыт) и ``ready``: apply не отказан гейтом, итог — ``ready``/``not_ready``."""
    pm = _pm_in("ready")
    if before == "booting":
        assert pm._run_apply("apply")[0].value == "booting"

    reply = _bounded(lambda: pm._cmd_topology_apply(_args()))

    assert reply.get("error") not in _REFUSAL_CODES, reply
    assert pm._run_snapshot()[0].value in {"ready", "not_ready"}
    assert pm._run_event.is_set() is False


@pytest.mark.timeout(120)
def test_apply_races_start_and_stop_one_consistent_outcome() -> None:
    """apply параллельно со START/STOP: отказ ``running`` допустим только если START прошёл; состояние не остаётся
    ``booting``; событие работы == (состояние == ``running``)."""
    for _round in range(10):
        pm = _pm_in("ready")
        replies: dict[str, dict] = {}
        barrier = threading.Barrier(3)
        errors: list[BaseException] = []

        def worker(name: str, fn) -> None:
            try:
                barrier.wait(10.0)
                replies[name] = fn()
            except BaseException as exc:  # noqa: BLE001 — в поток теста
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=("apply", lambda: pm._cmd_topology_apply(_args())), daemon=True),
            threading.Thread(target=worker, args=("start", pm._cmd_system_run_start), daemon=True),
            threading.Thread(target=worker, args=("stop", pm._cmd_system_run_stop), daemon=True),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join(20.0)
            assert not th.is_alive()
        assert not errors, errors

        state = pm._run_snapshot()[0].value
        assert state in {"ready", "not_ready", "running", "stopping"}, state
        assert pm._run_event.is_set() is (state in {"running"}), (state, replies)
        apply_error = replies["apply"].get("error")
        if apply_error in _REFUSAL_CODES:
            assert apply_error in {"running", "stopping"}, replies
            assert replies["start"].get("success") is True, replies


def test_hazard_helpers_are_importable() -> None:
    """Страховка обвязки: ``_pm_in`` отдаёт настоящий PM (иначе мок-тесты выше проверяли бы пустоту)."""
    assert isinstance(_pm_in("ready"), ProcessManagerProcess)
