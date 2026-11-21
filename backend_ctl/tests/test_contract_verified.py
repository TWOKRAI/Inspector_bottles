# -*- coding: utf-8 -*-
"""Контракт I3 «причинность проверки» (Task 0.3): слепой тест по приёмке лида.

Пять инструментов ``BackendDriver``, которые рапортуют «проверено». Контракт один:
хост ОТВЕРГ запись -> ключ успеха инструмента не может быть истинным; хост ПРИМЕНИЛ
запись, меняющую значение -> истинен. Подмена — на уровне ``send_command`` /
``system_command`` (хост отвергает как ``{"success": False, "error": "No handler for
<команда>"}``).

Каждый ``rejected`` сначала проверяет, что подставной хост ВИДЕЛ попытку записи, и
наличие ключа успеха в ответе, и только потом — что он ложен. Иначе тест был бы
зелёным и для инструмента, который ничего не послал или ответил без ключа.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from backend_ctl.driver import BackendDriver

TOOLS = [
    "set_register_verified",
    "register_restore",
    "config_reload_verified",
    "process_restart_verified",
    "telemetry_set",
]

# Ключи успеха из таблицы приёмки: все они должны быть и ложны (rejected), и истинны (accepted).
SUCCESS_KEYS: dict[str, tuple[str, ...]] = {
    "set_register_verified": ("success",),
    "register_restore": ("success",),
    "config_reload_verified": ("success",),
    "process_restart_verified": ("restarted",),
    "telemetry_set": ("success", "verified_effect"),
}


def _bounded[T](fn: Callable[[], T], limit: float = 5.0) -> T:
    """Вызов в daemon-потоке с дедлайном: зависший инструмент — красный тест, не зависший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["res"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(limit)
    assert not t.is_alive(), f"инструмент завис дольше {limit} с"
    if "exc" in box:
        raise box["exc"]
    return box["res"]


def _rejected(command: str) -> dict[str, Any]:
    return {"success": False, "error": f"No handler for {command}"}


# --------------------------------------------------------------------------
# set_register_verified / register_restore: регистр preprocessor/resize/target_width
# --------------------------------------------------------------------------


def _register_driver(
    monkeypatch, *, initial: int, host_applies: bool
) -> tuple[BackendDriver, list[dict[str, Any]], dict[str, dict[str, int]]]:
    d = BackendDriver()
    registers: dict[str, dict[str, int]] = {"resize": {"target_width": initial}}
    writes: list[dict[str, Any]] = []

    def fake_send(process, command, args=None, **kw):
        if command == "register_update":
            writes.append(dict(args))
            if not host_applies:
                return _rejected("register_update")
            registers[args["register"]][args["field"]] = args["value"]
            return {"success": True}
        if command == "introspect.registers":
            return {"success": True, "process": process, "registers": registers}
        raise AssertionError(f"неожиданная команда: {command}")

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, writes, registers


def _snapshot(value: int) -> dict[str, Any]:
    return {"processes": {"preprocessor": {"resize": {"target_width": value}}}}


def _scenario_set_register_verified(monkeypatch, *, host_applies: bool):
    initial = 5 if host_applies else 10
    d, writes, _regs = _register_driver(monkeypatch, initial=initial, host_applies=host_applies)
    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "target_width", 10))
    attempted = [w for w in writes if w.get("field") == "target_width" and w.get("value") == 10]
    return res, bool(attempted)


def _scenario_register_restore(monkeypatch, *, host_applies: bool):
    d, writes, _regs = _register_driver(monkeypatch, initial=5, host_applies=host_applies)
    res = _bounded(lambda: d.register_restore(_snapshot(10)))
    attempted = [w for w in writes if w.get("field") == "target_width" and w.get("value") == 10]
    return res, bool(attempted)


# --------------------------------------------------------------------------
# config_reload_verified
# --------------------------------------------------------------------------


def _plane(written: int, at: float = 100.0) -> dict[str, Any]:
    return {"channel_written_records": written, "at": at}


def _scenario_config_reload_verified(monkeypatch, *, host_applies: bool):
    d = BackendDriver()
    calls: list[str] = []

    def fake_send(process, command, args=None, **kw):
        calls.append(command)
        if command == "config.reload":
            if not host_applies:
                return _rejected("config.reload")
            return {
                "success": True,
                "result": {
                    "success": True,
                    "process": "lines",
                    "source": "inline",
                    "applied": {"log_level": "DEBUG"},
                    "counters": {"logger": _plane(10)},
                    "verified": {"verdict": "confirmed", "checked": 1, "mismatches": [], "unknown_keys": []},
                },
            }
        if command == "introspect.observability":
            return {
                "success": True,
                "result": {"success": True, "counters": {"logger": _plane(40, at=101.0)}},
            }
        return {"success": True, "result": {"success": True}}

    monkeypatch.setattr(d, "send_command", fake_send)
    res = _bounded(lambda: d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0))
    return res, "config.reload" in calls


# --------------------------------------------------------------------------
# process_restart_verified
# --------------------------------------------------------------------------


def _supervision_entry(pid: int, *, restarts: int) -> dict[str, Any]:
    return {
        "incarnation": 0,
        "restart_count": 0,
        "last_exit": None,
        "status": "running",
        "pid": pid,
        "alive": True,
        "started_at": 1000.0,
        "instance_restarts": restarts,
        "stop_outcome": None,
    }


def _scenario_process_restart_verified(monkeypatch, *, host_applies: bool):
    d = BackendDriver()
    snapshots = (
        [_supervision_entry(100, restarts=0), _supervision_entry(200, restarts=1)]
        if host_applies
        else [_supervision_entry(100, restarts=0)]
    )
    state = {"i": 0}
    system_calls: list[tuple[Any, Any]] = []

    def fake_send(process, command, args=None, **kw):
        if command == "supervision.status":
            idx = min(state["i"], len(snapshots) - 1)
            state["i"] += 1
            return {
                "success": True,
                "result": {"success": True, "epoch": 0, "processes": {"lines": snapshots[idx]}},
            }
        return {"success": True, "result": {"success": True}}

    def fake_system(command, timeout=None):
        system_calls.append((command.get("cmd"), command.get("process_name")))
        if not host_applies:
            return _rejected("process.restart")
        return {"success": True, "outcome": "exited"}

    monkeypatch.setattr(d, "send_command", fake_send)
    monkeypatch.setattr(d, "system_command", fake_system)
    wait = 2.0 if host_applies else 1.0  # опрос спит по 0.5 с
    res = _bounded(lambda: d.process_restart_verified("lines", wait=wait))
    return res, ("process.restart", "lines") in system_calls


# --------------------------------------------------------------------------
# telemetry_set(verify=True)
# --------------------------------------------------------------------------


def _telemetry_readback(enabled: bool) -> dict[str, Any]:
    """Метрика fps есть и в ``resolved``, и в сырой ``publish.metrics`` — иначе сработает
    защита «значение совпало с дефолтом» и тест зелёный по другой причине."""
    return {
        "success": True,
        "process": "camera_0",
        "gate_active": True,
        "publish": {"metrics": {"fps": {}}},
        "resolved": {"fps": {"enabled": enabled, "interval_sec": 1.0}},
        "unknown_metrics": [],
        "gated_metrics": ["fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm"],
        "throttle_rules": None,
    }


def _scenario_telemetry_set(monkeypatch, *, host_applies: bool):
    d = BackendDriver()
    # rejected: правило fps.enabled False уже действует; accepted: True -> False.
    live = {"enabled": False if not host_applies else True}
    calls: list[tuple[Any, str, Any]] = []

    def fake_send(process, command, args=None, **kw):
        calls.append((process, command, args))
        if command == "introspect.telemetry":
            return {"success": True, "result": _telemetry_readback(live["enabled"])}
        if command == "telemetry.broadcast":
            if not host_applies:
                return _rejected("telemetry.broadcast")
            live["enabled"] = False
            return {
                "success": True,
                "result": {
                    "success": True,
                    "process": "ProcessManager",
                    "publish": {
                        "requested": True,
                        "target_count": 1,
                        "reached": 1,
                        "targets": ["camera_0"],
                        "complete": True,
                        "semantics": "delivered",
                    },
                },
            }
        return {"success": True, "result": {"success": True}}

    monkeypatch.setattr(d, "send_command", fake_send)
    res = _bounded(lambda: d.telemetry_set("camera_0", "fps", enabled=False, verify=True, verify_within=0.0))
    return res, ("ProcessManager", "telemetry.broadcast") in [(p, c) for p, c, _a in calls]


SCENARIOS: dict[str, Callable[..., tuple[Any, bool]]] = {
    "set_register_verified": _scenario_set_register_verified,
    "register_restore": _scenario_register_restore,
    "config_reload_verified": _scenario_config_reload_verified,
    "process_restart_verified": _scenario_process_restart_verified,
    "telemetry_set": _scenario_telemetry_set,
}


# --------------------------------------------------------------------------
# Контракт
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS)
def test_rejected_write_not_success(tool: str, monkeypatch) -> None:
    """Хост отверг запись -> ключ успеха инструмента ложен (а не «значение и так равно»)."""
    res, attempted = SCENARIOS[tool](monkeypatch, host_applies=False)

    assert attempted, f"{tool}: подставной хост не увидел попытки записи"
    for key in SUCCESS_KEYS[tool]:
        assert key in res, f"{tool}: в ответе нет ключа успеха {key!r}: {res!r}"
    for key in SUCCESS_KEYS[tool]:
        assert res[key] is False, f"{tool}: {key}={res[key]!r} при отвергнутой записи: {res!r}"

    if tool == "config_reload_verified":
        assert res.get("verdict") != "confirmed", res
    if tool == "register_restore":
        assert res["written"] == 1, res


@pytest.mark.parametrize("tool", TOOLS)
def test_accepted_write_from_other_value_success(tool: str, monkeypatch) -> None:
    """Хост применил запись, меняющую значение -> ключ успеха истинен (контроль против «всегда False»)."""
    res, attempted = SCENARIOS[tool](monkeypatch, host_applies=True)

    assert attempted, f"{tool}: подставной хост не увидел попытки записи"
    for key in SUCCESS_KEYS[tool]:
        assert key in res, f"{tool}: в ответе нет ключа успеха {key!r}: {res!r}"
    for key in SUCCESS_KEYS[tool]:
        assert res[key] is True, f"{tool}: {key}={res[key]!r} при применённой записи: {res!r}"

    if tool == "config_reload_verified":
        assert res["verdict"] == "confirmed", res


def test_restore_equal_state_reports_vacuous(monkeypatch) -> None:
    """Поле 10, снимок 10: записи нет — честный пустой restore, вслух названный vacuous."""
    d, writes, _regs = _register_driver(monkeypatch, initial=10, host_applies=True)
    res = _bounded(lambda: d.register_restore(_snapshot(10)))

    assert "vacuous" in res, f"нет ключа vacuous: {res!r}"
    assert writes == [], f"register_update не должен отправляться: {writes!r}"
    assert res["written"] == 0, res
    assert res["success"] is True, res
    assert res["vacuous"] == 1, res
