# -*- coding: utf-8 -*-
"""Срез S3b1 (run-state 2.7) — авторские hazard-тесты: границы ``run_config_value``, тексты WARNING, публикация листьев.

Слепой набор ``test_run_config_and_view.py`` держит контракт; здесь — то, что он не покрывает: странные входы
``run_config_value`` (не бросает), тексты WARNING геттеров PM дословно и без значения входа, дедупликация
публикации листьев (в том числе новых ``run_gate`` / ``stop_allowed``), «читается один раз» для ``run_gate``.
Ожидаемые значения — литералы. Импорты новых имён — внутри тестов (красный прогон до правки ``src``).
"""

from __future__ import annotations

import pytest

from .test_run_commands import _Store, make_run_pm

_MARKER = "ZZ-marker-value"


def _warnings(pm) -> list[str]:
    return [str(call) for call in pm._log_warning.call_args_list]


# --------------------------------------------------------------------------- #
# run_config_value: не бросает, не отдаёт вход
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [{}, [], (), b"1", object(), float("nan"), float("-inf"), 10**400, "", 0.0, -0.0],
    ids=["dict", "list", "tuple", "bytes", "object", "nan", "-inf", "huge-int", "empty-str", "zero", "neg-zero"],
)
@pytest.mark.parametrize("key", ["run_stop_timeout_s", "run_restart_grace_s"])
def test_numeric_odd_input_never_raises_and_gives_default(key: str, raw: object) -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import run_config_value

    default = 10.0 if key == "run_stop_timeout_s" else 30.0
    assert run_config_value(key, raw) == (default, False)


@pytest.mark.parametrize(
    "raw", [0, "", [], {}, "false", float("nan")], ids=["int0", "empty", "list", "dict", "str", "nan"]
)
def test_run_gate_odd_input_is_default_and_not_ok(raw: object) -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import run_config_value

    assert run_config_value("run_gate", raw) == (False, False)
    assert run_config_value("run_autostart", raw) == (False, False)


def test_run_gate_false_is_valid_not_default_fallback() -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_config import run_config_value

    assert run_config_value("run_gate", False) == (False, True)
    assert run_config_value("run_autostart", None) == (False, True)


def test_model_rejects_bad_numeric_but_keeps_unset_fields_unset() -> None:
    """Ф5: у наследника в ``exclude_unset`` попадают только заданные ключи (проводка S3b2 на этом стоит)."""
    from multiprocess_framework.modules.process_manager_module.process.run_config import RunConfig

    assert RunConfig(run_gate=True).model_dump(include={"run_gate", "run_stop_timeout_s"}, exclude_unset=True) == {
        "run_gate": True
    }


# --------------------------------------------------------------------------- #
# Тексты WARNING геттеров PM: дословно, без значения входа
# --------------------------------------------------------------------------- #


def test_run_gate_warning_text_verbatim() -> None:
    pm = make_run_pm(_MARKER)
    assert [w for w in _warnings(pm) if "run_gate" in w] == [
        "call('run_gate негоден (нужно true или false) — гейт работы выключен')"
    ]
    assert pm._run_gate is False


def test_restart_grace_bad_value_text_and_default() -> None:
    pm = make_run_pm(True)
    pm.update_config("run_restart_grace_s", _MARKER)
    assert pm._run_restart_grace() == 30.0
    texts = [w for w in _warnings(pm) if "run_restart_grace_s" in w]
    assert texts == ["call('run_restart_grace_s негоден (нужно число > 0) — взято 30.0 с')"], texts
    assert not [w for w in _warnings(pm) if _MARKER in w]


def test_stop_timeout_bad_value_text_and_default() -> None:
    pm = make_run_pm(True)
    pm.update_config("run_stop_timeout_s", _MARKER)
    assert pm._run_stop_timeout() == 10.0
    texts = [w for w in _warnings(pm) if "run_stop_timeout_s" in w]
    assert texts == ["call('run_stop_timeout_s негоден (нужно число > 0) — взято 10.0 с')"], texts
    assert not [w for w in _warnings(pm) if _MARKER in w]


@pytest.mark.parametrize("raw", [True, 0, -3, float("inf"), "5"], ids=["bool", "zero", "negative", "inf", "str"])
def test_getters_reject_what_run_config_rejects(raw: object) -> None:
    pm = make_run_pm(True)
    pm.update_config("run_stop_timeout_s", raw)
    pm.update_config("run_restart_grace_s", raw)
    assert pm._run_stop_timeout() == 10.0
    assert pm._run_restart_grace() == 30.0


def test_getters_read_every_time_not_once() -> None:
    """Числовые ключи читаются при каждом использовании (в отличие от ``run_gate``)."""
    pm = make_run_pm(True)
    assert pm._run_stop_timeout() == 10.0
    pm.update_config("run_stop_timeout_s", 2)
    pm.update_config("run_restart_grace_s", 45)
    assert pm._run_stop_timeout() == 2.0
    assert pm._run_restart_grace() == 45.0


def test_default_constants_are_literals() -> None:
    from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
        ProcessManagerProcess,
    )

    assert ProcessManagerProcess._DEFAULT_RUN_STOP_TIMEOUT_S == 10.0
    assert ProcessManagerProcess._DEFAULT_RUN_RESTART_GRACE_S == 30.0


def test_run_gate_read_once_config_update_does_not_change_it() -> None:
    """ADR-PMM-049: ``run_gate`` читается один раз в ``_create_components()``; позднее ``update_config`` не меняет."""
    pm = make_run_pm(False)
    pm.update_config("run_gate", True)
    assert pm._run_gate is False
    assert pm._cmd_system_run_status()["run_gate"] is False


# --------------------------------------------------------------------------- #
# run_view: таблица по всем состояниям
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("state_name", "start", "stop"),
    [
        ("booting", False, False),
        ("not_ready", False, False),
        ("ready", True, False),
        ("running", False, True),
        ("stopping", False, False),
        ("fault", False, False),
        ("shutting_down", False, False),
    ],
)
def test_run_view_start_stop_allowed_per_state(state_name: str, start: bool, stop: bool) -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_state import RunState, run_view

    view = run_view(RunState(state_name), 0.0, run_gate=False, ack_allowed=True, reasons=[], last_fault=None)
    assert (view["start_allowed"], view["stop_allowed"]) == (start, stop), view
    assert view["state"] == state_name
    assert view["ack_allowed"] is True
    assert view["run_gate"] is False


def test_run_view_keeps_reasons_and_last_fault_as_given() -> None:
    from multiprocess_framework.modules.process_manager_module.process.run_state import RunState, run_view

    reasons = [{"node": "cam", "severity": "failure", "reason": "r", "source": "report"}]
    fault = {"at": 1.0, "reasons": reasons, "acknowledged_at": None}
    view = run_view(RunState.fault, 3.0, run_gate=True, ack_allowed=False, reasons=reasons, last_fault=fault)
    assert view["reasons"] == reasons
    assert view["last_fault"] == fault
    assert view["since"] == 3.0


# --------------------------------------------------------------------------- #
# Публикация листьев: дедупликация, новые листья пишутся один раз
# --------------------------------------------------------------------------- #


def test_publish_writes_each_leaf_once_and_new_leaves_present() -> None:
    pm = make_run_pm(True)
    store = _Store()
    pm._state_store_manager = store

    pm._publish_run_state()
    first = list(store.writes)
    paths = [p for p, _ in first]
    assert sorted(paths) == sorted(
        f"system.run.{k}"
        for k in ("state", "since", "run_gate", "start_allowed", "stop_allowed", "ack_allowed", "reasons", "last_fault")
    ), paths
    assert len(paths) == len(set(paths)), paths  # ни один лист не записан дважды

    pm._publish_run_state()
    assert store.writes == first  # повтор без изменений ничего не пишет


def test_publish_after_start_rewrites_only_changed_leaves() -> None:
    pm = make_run_pm(True)
    store = _Store()
    pm._state_store_manager = store
    pm._publish_run_state()
    before = len(store.writes)

    assert pm._cmd_system_run_start()["success"] is True
    changed = {p for p, _ in store.writes[before:]}
    assert {"system.run.state", "system.run.since", "system.run.start_allowed", "system.run.stop_allowed"} <= changed
    assert "system.run.run_gate" not in changed  # не менялся: не переписывается
    assert store.values("system.run.stop_allowed")[-1] is True
    assert store.values("system.run.start_allowed")[-1] is False


def test_run_gate_leaf_false_when_gate_off() -> None:
    pm = make_run_pm(False)
    store = _Store()
    pm._state_store_manager = store
    pm._publish_run_state()
    assert store.values("system.run.run_gate") == [False]
    assert store.values("system.run.stop_allowed") == [False]
