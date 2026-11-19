# -*- coding: utf-8 -*-
"""Срез S3b1 (run-state 2.7) — слепые приёмочные тесты: ключи работы PM одной моделью и один построитель вида.

Контракт — бриф слепого tester (литералы оттуда). Новые имена (``run_config``, ``run_view``) — импорт ВНУТРИ тестов:
ошибка импорта роняет только свой тест, контроли (3 и 6) прогоняются на базе.

Решения тестера (ASSUMPTION):
  * текст WARNING берётся целиком из вызова ``pm._log_warning`` (``str(call)``: позиционные и именованные аргументы);
  * тест 5 сравнивает последнюю запись каждого записанного листа ``system.run.<k>`` с ответом ``status``;
    обязательны листья ``state``, ``run_gate``, ``stop_allowed`` (иначе сравнение пусто);
  * ``stop()`` стенда уже ограничен daemon-потоком с дедлайном; ожидание выхода из ``stopping`` — ``wait_not_stopping``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from .test_run_commands import _Store, make_run_pm
from .test_run_stop import rig_factory  # noqa: F401 — фикстура стенда остановки

_VALUE_MARKER = "ZZ-marker-value"
_STATUS_KEYS = {
    "state",
    "since",
    "run_gate",
    "start_allowed",
    "stop_allowed",
    "ack_allowed",
    "reasons",
    "last_fault",
}


def _warnings(pm: Any) -> list[str]:
    return [str(call) for call in pm._log_warning.call_args_list]


# --------------------------------------------------------------------------- #
# 1. Числовые ключи: годное значение / умолчание + признак «негодно»
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("key", "default"),
    [("run_stop_timeout_s", 10.0), ("run_restart_grace_s", 30.0)],
)
@pytest.mark.parametrize(
    ("raw", "use_default", "expected_ok"),
    [
        (10, False, True),
        (0.5, False, True),
        (None, True, True),
        (0, True, False),
        (-1, True, False),
        (True, True, False),
        ("2", True, False),
        (float("inf"), True, False),
    ],
    ids=["int10", "float0.5", "none", "zero", "negative", "bool", "str", "inf"],
)
def test_run_config_value_numeric(key: str, default: float, raw: object, use_default: bool, expected_ok: bool) -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import run_config_value

    result = run_config_value(key, raw)
    expected_value = default if use_default else float(raw)  # type: ignore[arg-type]
    assert result == (expected_value, expected_ok), result
    assert isinstance(result[0], float), type(result[0])


def test_run_config_keys_literal() -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import RUN_CONFIG_KEYS

    assert RUN_CONFIG_KEYS == ("run_gate", "run_autostart", "run_stop_timeout_s", "run_restart_grace_s")


def test_run_config_defaults_literal() -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import RunConfig

    assert RunConfig().model_dump() == {
        "run_gate": False,
        "run_autostart": False,
        "run_stop_timeout_s": 10.0,
        "run_restart_grace_s": 30.0,
    }


# --------------------------------------------------------------------------- #
# 2. run_gate: строго bool
# --------------------------------------------------------------------------- #


def test_run_config_value_run_gate_true() -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import run_config_value

    assert run_config_value("run_gate", True) == (True, True)


@pytest.mark.parametrize("raw", [1, "true", "yes"], ids=["int1", "str-true", "str-yes"])
def test_run_config_value_run_gate_non_bool_rejected(raw: object) -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import run_config_value

    assert run_config_value("run_gate", raw) == (False, False)


# --------------------------------------------------------------------------- #
# 3. КОНТРОЛЬ (зелёный на базе): негодный run_gate -> одно WARNING с ключом, без значения
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_bad_run_gate_one_warning_without_value() -> None:
    pm = make_run_pm(_VALUE_MARKER)
    warnings = _warnings(pm)
    with_key = [w for w in warnings if "run_gate" in w]
    assert len(with_key) == 1, warnings
    assert not [w for w in warnings if _VALUE_MARKER in w], warnings


# --------------------------------------------------------------------------- #
# 4. run_view / ответ status: stop_allowed
# --------------------------------------------------------------------------- #


def test_run_view_running_literal() -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_state import RunState, run_view

    view = run_view(RunState.running, 12.5, run_gate=True, ack_allowed=False, reasons=[], last_fault=None)
    expected = {
        "state": "running",
        "since": 12.5,
        "run_gate": True,
        "start_allowed": False,
        "stop_allowed": True,
        "ack_allowed": False,
        "reasons": [],
        "last_fault": None,
    }
    assert view == expected, view
    assert list(view) == [
        "state",
        "since",
        "run_gate",
        "start_allowed",
        "stop_allowed",
        "ack_allowed",
        "reasons",
        "last_fault",
    ], list(view)


def test_run_view_ready_start_allowed_stop_not() -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_state import RunState, run_view

    view = run_view(RunState.ready, 1.0, run_gate=True, ack_allowed=False, reasons=[], last_fault=None)
    assert view["start_allowed"] is True, view
    assert view["stop_allowed"] is False, view


@pytest.mark.timeout(60)
def test_status_has_stop_allowed_follows_running() -> None:
    pm = make_run_pm(True)
    status = pm._cmd_system_run_status()
    assert set(status) == _STATUS_KEYS, status
    assert status["state"] == "ready", status
    assert status["stop_allowed"] is False, status

    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    after = pm._cmd_system_run_status()
    assert after["state"] == "running", after
    assert after["stop_allowed"] is True, after


@pytest.mark.timeout(60)
def test_rig_stop_allowed_running_then_ready(rig_factory) -> None:  # noqa: F811
    rig = rig_factory(("cam",))
    rig.to_running()
    running = rig.status()
    assert running["state"] == "running", running
    assert running["stop_allowed"] is True, running

    rig.stop()
    assert rig.wait_not_stopping(6.0), "STOP не завершился"
    done = rig.status()
    assert done["state"] == "ready", done
    assert done["stop_allowed"] is False, done


# --------------------------------------------------------------------------- #
# 5. Листья стора строятся тем же построителем
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_store_leaves_match_status() -> None:
    pm = make_run_pm(True)
    store = _Store()
    pm._state_store_manager = store

    assert pm._cmd_system_run_start()["success"] is True

    assert ("system.run.run_gate", True) in store.writes, store.writes
    assert ("system.run.stop_allowed", True) in store.writes, store.writes

    status = pm._cmd_system_run_status()
    compared = []
    for key, value in status.items():
        written = store.values(f"system.run.{key}")
        if written:
            compared.append(key)
            assert written[-1] == value, (key, written[-1], value)
    assert {"state", "run_gate", "stop_allowed"} <= set(compared), compared


# --------------------------------------------------------------------------- #
# 6. КОНТРОЛЬ (зелёный на базе): срок остановки — run_stop_timeout_s; негодный -> умолчание 10 с, без значения в тексте
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_timeout_honoured_valid_value(rig_factory) -> None:  # noqa: F811
    rig = rig_factory(("cam", "plc"), timeout_s=0.3)
    rig.sim.set("plc", mode="stuck")
    rig.to_running()

    t0 = time.monotonic()
    rig.stop()
    assert rig.wait_not_stopping(6.0), "STOP не завершился по сроку"
    elapsed = time.monotonic() - t0
    assert 0.25 <= elapsed < 5.0, f"выход из stopping за {elapsed:.2f} с, ждали 0.25..5.0 с"


@pytest.mark.timeout(60)
def test_stop_timeout_bad_value_default_and_warning_without_value(rig_factory) -> None:  # noqa: F811
    rig = rig_factory(("cam", "plc"), timeout_s="abc")
    rig.sim.set("plc", mode="stuck")
    rig.to_running()

    t0 = time.monotonic()
    rig.stop()
    assert rig.wait_not_stopping(15.0), "STOP не завершился за 15 с"
    elapsed = time.monotonic() - t0
    assert elapsed >= 9.5, f"выход из stopping за {elapsed:.2f} с — раньше умолчания 10 с"

    warnings = _warnings(rig.pm)
    assert [w for w in warnings if "run_stop_timeout_s" in w], warnings
    assert not [w for w in warnings if "abc" in w], warnings
