# -*- coding: utf-8 -*-
"""C-64 — слепая приёмка: отказ или пустое переключение топологии не оставляет провода ``broken``.

Написано ДО реализации; реализация (``process_manager_process.py``, ``topology_manager.py``) не читалась.

Контракт: ProcessManager заводит провода командой ``wire.setup`` и показывает их статус наружу — ответ команды
``wire.status``, пути state ``system.health.broken_wires`` и ``system.wires.<key>.status``. После ``apply_topology``:

  * ни один процесс не тронут (отказ до исполнения команд или «изменений нет») -> провод показывает тот статус,
    что был до вызова;
  * процессы пересозданы откатом -> каждый получает ``wire.configure`` со своей ролью, провод снова ``active``;
  * пока переключение идёт, провод показан как ``broken`` (прежнее поведение, остаётся).

Обвязка: ``make_pm`` из conftest (двойники процессов) + ``pm.send_message = MagicMock()``; публикацию состояния
делает настоящий ``ProcessMonitor`` (как ``_monitor_with_wires`` в ``test_wire_reissue.py``). R6 — настоящие
spawn-дети через ``running_rig`` из ``test_per_child_stop_window_acceptance.py``. Ожидаемые значения — литералы.
Всё, что может блокироваться, идёт в daemon-потоке с ``join``-дедлайном.

Ожидание на дереве до реализации: RED R1-R6; стражи S1-S3 зелёные.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

from ..monitor.process_monitor import ProcessMonitor
from ._lifecycle_fifo_helpers import LIFECYCLE_CHILD_CLASS_PATH
from .conftest import make_pm
from .test_per_child_stop_window_acceptance import child, running_rig

WIRE_KEY = "cam->proc"
STATE_BROKEN_PATH = "system.health.broken_wires"
STATE_STATUS_PATH = f"system.wires.{WIRE_KEY}.status"

CALL_DEADLINE_S = 30.0  # потолок блокирующего вызова apply_topology на двойниках
POLL_DEADLINE_S = 10.0  # опрос wire.status у настоящих детей (R6)

BLUEPRINT = {
    "processes": [
        {"process_name": "cam", "process_class": "x.Cam"},
        {"process_name": "proc", "process_class": "x.Proc"},
    ]
}


# --------------------------------------------------------------------------- #
# Обвязка
# --------------------------------------------------------------------------- #


def _run_with_deadline(fn: Callable[[], Any], deadline_s: float, what: str) -> Any:
    """Блокирующий вызов в daemon-потоке: результат или исключение вызова; зависание -> упавший ассерт."""
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение вызова возвращаем тесту, не глотаем
            box["error"] = exc

    th = threading.Thread(target=_target, daemon=True, name=f"c64-{what}")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"{what} не вернулся за {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["result"]


def _pm_with_wire() -> Any:
    """PM с процессами cam/proc, заведённым проводом cam->proc (direct) и обнулённым журналом send_message."""
    pm = make_pm({"cam": {"class": "x.Cam"}, "proc": {"class": "x.Proc"}})
    pm.send_message = MagicMock()
    setup = pm._cmd_wire_setup(wire_key=WIRE_KEY, source_process="cam", target_process="proc", transport="direct")
    assert setup["success"] is True, f"предусловие: wire.setup не удался: {setup}"
    assert pm._cmd_wire_status()["wires"][WIRE_KEY]["status"] == "active", "предусловие: провод не active"
    pm.send_message.reset_mock()  # wire.setup сам шлёт wire.configure — до вызова apply эти отправки не считаем
    return pm


def _wire_status(pm: Any) -> str:
    return pm._cmd_wire_status()["wires"][WIRE_KEY]["status"]


def _published(pm: Any) -> dict[str, Any]:
    """Публикация настоящего ``ProcessMonitor`` поверх ``pm._active_wires`` и ``pm._process_registry``."""
    published: dict[str, Any] = {}
    host = MagicMock()
    host.name = "ProcessManager"
    host._active_wires = pm._active_wires
    host._process_registry = pm._process_registry
    host.worker_manager.create_worker = lambda *a, **kw: None
    ssm = MagicMock()

    def _set(payload: dict) -> None:
        data = payload["data"]
        published[data["path"]] = data["value"]

    ssm.handle_state_set.side_effect = _set
    ssm.handle_state_get.return_value = {"status": "error"}
    host._state_store_manager = ssm
    ProcessMonitor(host)._publish_health({})
    return published


def _configure_calls(pm: Any) -> list[tuple[str, str]]:
    """Отправки ``wire.configure`` как (адресат, роль), отсортированные."""
    calls = []
    for call in pm.send_message.call_args_list:
        target, cmd = call[0][0], call[0][1]
        if cmd.get("command") == "wire.configure":
            calls.append((target, cmd["data"]["role"]))
    return sorted(calls)


def _fail_on_second_create(pm: Any) -> None:
    """Отказ на 2-м вызове ``create`` через шов менеджера топологии (подмена ``pm._topology_create`` не сработает)."""
    original = pm._topology_create
    count = {"n": 0}

    def failing_create(name: str, proc_dict: dict) -> bool:
        count["n"] += 1
        if count["n"] == 2:
            raise RuntimeError(f"injected failure on create #{count['n']} ({name})")
        return original(name, proc_dict)

    pm._topology_manager.configure(create_process_fn=failing_create)


def _fail_before_commands(pm: Any) -> None:
    def invalid_blueprint(diff_result: dict, desired: dict) -> list[dict]:
        raise RuntimeError("BlueprintInvalid")

    pm._topology_manager.configure(commands_fn=invalid_blueprint)


def _apply(pm: Any) -> dict:
    return _run_with_deadline(lambda: pm.apply_topology(BLUEPRINT), CALL_DEADLINE_S, "apply_topology")


def _assert_wire_shown(pm: Any, status: str, broken: int, *, ctx: str) -> None:
    published = _published(pm)
    observed = (
        f"{ctx}: wire.status={_wire_status(pm)!r}, {STATE_BROKEN_PATH}={published.get(STATE_BROKEN_PATH)!r}, "
        f"{STATE_STATUS_PATH}={published.get(STATE_STATUS_PATH)!r}"
    )
    assert _wire_status(pm) == status, observed
    assert published.get(STATE_BROKEN_PATH) == broken, observed
    assert published.get(STATE_STATUS_PATH) == status, observed


# --------------------------------------------------------------------------- #
# R1-R5: двойники
# --------------------------------------------------------------------------- #


def test_refused_before_commands_wire_stays_active() -> None:
    """R1: отказ до команд (commands_fn бросает) -> процессы не тронуты, провод ``active``, ``wire.configure`` нет.

    До: ``broken``, ``broken_wires`` 1."""
    pm = _pm_with_wire()
    cam = pm._process_registry.get_process_by_name("cam")
    proc = pm._process_registry.get_process_by_name("proc")
    _fail_before_commands(pm)

    result = _apply(pm)

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert pm._process_registry.get_process_by_name("cam") is cam
    assert pm._process_registry.get_process_by_name("proc") is proc
    _assert_wire_shown(pm, "active", 0, ctx="после отказа до команд")
    assert _configure_calls(pm) == [], f"wire.configure отправлен: {_configure_calls(pm)}"


def test_failed_create_rollback_reissues_wire() -> None:
    """R2: отказ на 2-м создании -> откат пересоздал процессы -> ``wire.configure`` cam=sender, proc=receiver.

    До: ``broken``, ``broken_wires`` 1, отправок нет."""
    pm = _pm_with_wire()
    _fail_on_second_create(pm)

    result = _apply(pm)

    assert result["success"] is False
    assert result["rolled_back"] is True
    _assert_wire_shown(pm, "active", 0, ctx="после отката по отказу create")
    assert _configure_calls(pm) == [("cam", "sender"), ("proc", "receiver")], f"wire.configure: {_configure_calls(pm)}"


def test_exception_in_apply_rollback_reissues_wire() -> None:
    """R3: исключение из ``TopologyManager.apply`` -> те же ожидания, что R2. До: ``broken``, 1, отправок нет."""
    pm = _pm_with_wire()
    pm._topology_manager.apply = MagicMock(side_effect=RuntimeError("outside apply"))

    result = _apply(pm)

    assert result["success"] is False
    assert result["rolled_back"] is True
    _assert_wire_shown(pm, "active", 0, ctx="после исключения вне apply")
    assert _configure_calls(pm) == [("cam", "sender"), ("proc", "receiver")], f"wire.configure: {_configure_calls(pm)}"


def test_no_changes_wire_stays_active() -> None:
    """R4: «изменений нет» (``has_changes`` False) -> ``success`` True, ``applied`` 0, провод ``active``, отправок нет.

    До: ``broken``, 1."""
    pm = _pm_with_wire()
    pm._topology_manager.configure(diff_fn=lambda cur, new: {"has_changes": False})

    result = _apply(pm)

    assert result["success"] is True
    assert result["applied"] == 0, f"applied={result['applied']!r}"
    _assert_wire_shown(pm, "active", 0, ctx="после «изменений нет»")
    assert _configure_calls(pm) == [], f"wire.configure отправлен: {_configure_calls(pm)}"


def test_refused_before_commands_keeps_pending_status() -> None:
    """R5: статус перед вызовом ``pending`` + отказ до команд -> ``pending`` сохраняется.

    До: ``broken``."""
    pm = _pm_with_wire()
    pm._active_wires[WIRE_KEY]["status"] = "pending"
    _fail_before_commands(pm)

    _apply(pm)

    published = _published(pm)
    observed = (
        f"wire.status={_wire_status(pm)!r}, {STATE_BROKEN_PATH}={published.get(STATE_BROKEN_PATH)!r}, "
        f"{STATE_STATUS_PATH}={published.get(STATE_STATUS_PATH)!r}"
    )
    assert _wire_status(pm) == "pending", observed
    assert published.get(STATE_BROKEN_PATH) == 0, observed


# --------------------------------------------------------------------------- #
# R6: настоящие дети
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
def test_real_child_rollback_wire_returns(tmp_path: Path) -> None:
    """R6: настоящие spawn-дети, отказ на 2-м создании в ``topology.apply`` -> откат -> ``wire.status`` ``active``
    при опросе до 10,0 с. До: ``broken`` во всех опросах."""
    children = {"cam": child(), "proc": child()}
    blueprint = {
        "processes": [
            {"process_name": "cam", "process_class": LIFECYCLE_CHILD_CLASS_PATH},
            {"process_name": "proc", "process_class": LIFECYCLE_CHILD_CLASS_PATH},
        ]
    }

    with running_rig(tmp_path, children) as rig:

        def scenario() -> tuple[Any, Any, list[str]]:
            setup_sent = rig.send(
                "wire.setup",
                {"wire_key": WIRE_KEY, "source_process": "cam", "target_process": "proc", "transport": "direct"},
            )
            setup = rig.wait_reply(setup_sent)
            if setup is None:
                return None, None, []

            original = rig.pm._topology_create
            count = {"n": 0}

            def failing_create(name: str, proc_dict: dict) -> bool:
                count["n"] += 1
                if count["n"] == 2:
                    raise RuntimeError(f"injected failure on create #{count['n']} ({name})")
                return original(name, proc_dict)

            rig.pm._topology_manager.configure(create_process_fn=failing_create)

            applied = rig.wait_reply(rig.send("topology.apply", {"topology_dict": blueprint}))

            seen: list[str] = []
            end = time.monotonic() + POLL_DEADLINE_S
            while time.monotonic() < end:
                reply = rig.wait_reply(rig.send("wire.status"), timeout=5.0)
                wires = (reply.result or {}).get("wires", {}) if reply is not None else {}
                status = wires.get(WIRE_KEY, {}).get("status")
                seen.append(str(status))
                if status == "active":
                    break
                time.sleep(0.2)
            return setup, applied, seen

        setup, applied, seen = _run_with_deadline(scenario, 150.0, "сценарий R6")

    assert setup is not None, "wire.setup не ответил за дедлайн"
    assert applied is not None, "topology.apply не ответил за дедлайн"
    result = applied.result
    assert isinstance(result, dict) and result.get("success") is False, f"topology.apply: {result}"
    assert result.get("rolled_back") is True, f"topology.apply: {result}"
    assert "active" in seen, f"wire.status за {POLL_DEADLINE_S} с: {len(seen)} опросов, последний {seen[-1:]!r}"


# --------------------------------------------------------------------------- #
# Стражи (зелёные до и после)
# --------------------------------------------------------------------------- #


def test_successful_switch_reissues_wire() -> None:
    """S1: успешное переключение без инъекций -> ``active``, 0, ``wire.configure`` ровно 2 (cam и proc)."""
    pm = _pm_with_wire()

    result = _apply(pm)

    assert result["success"] is True
    _assert_wire_shown(pm, "active", 0, ctx="после успешного переключения")
    calls = _configure_calls(pm)
    assert len(calls) == 2, f"wire.configure: {calls}"
    assert sorted(target for target, _role in calls) == ["cam", "proc"], f"wire.configure: {calls}"


def test_switch_window_reports_broken() -> None:
    """S2: в окне переключения (внутри ``commands_fn``) ``wire.status`` показывает ``broken``."""
    pm = _pm_with_wire()
    snapped: list[str] = []

    def commands_fn(diff_result: dict, desired: dict) -> list[dict]:
        snapped.append(_wire_status(pm))
        raise RuntimeError("BlueprintInvalid")

    pm._topology_manager.configure(commands_fn=commands_fn)

    _apply(pm)

    assert snapped == ["broken"], f"wire.status в окне переключения: {snapped}"


def test_reissue_disabled_rollback_sends_nothing() -> None:
    """S3: ``wire_reissue_enabled`` False + отказ на 2-м создании -> статус ``active``, ``wire.configure`` нет."""
    pm = _pm_with_wire()
    base_get_config = pm.get_config

    def _cfg(key: str, default: Any = None) -> Any:
        if key == "wire_reissue_enabled":
            return False
        return base_get_config(key, default)

    pm.get_config = _cfg
    _fail_on_second_create(pm)

    _apply(pm)

    assert _wire_status(pm) == "active", f"wire.status={_wire_status(pm)!r}"
    assert _configure_calls(pm) == [], f"wire.configure отправлен: {_configure_calls(pm)}"
