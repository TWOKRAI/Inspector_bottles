# -*- coding: utf-8 -*-
"""Task 1.8 (system-run-state) — слепые приёмочные тесты автоперезапуска процесса в работе на уровне PM.

Контракт (из брифа задачи; interface.py нет): флаг ``run_auto_restart`` внутри сырого ``restart_policy`` процесса
(``_process_configs[name]["restart_policy"]``). Процесс с флагом, упавший в ``running``, не роняет систему в
``fault``, пока супервизор его перезапускает (причина ``out_of_spec`` «перезапуск <процесс>»); ``fault`` — когда окно
``run_restart_grace_s`` (конфиг PM, умолчание 30.0) истекло или супервизор отказался (``status == "failed"`` в
настоящем снимке монитора). Флаг без ``enabled: true`` — ``failure`` источника ``config``. Ребёнок после рестарта
наследует взведённый ``run_event``.

Обвязка — настоящие объекты, как в ``test_run_commands.py``: ``make_readiness_pm`` (``ProcessManagerProcess`` +
настоящий ``ProcessMonitor``), такт ``monitor._run_iteration()``. Падение процесса — ``_alive = False`` у двойника
процесса реестра (+ ``exitcode``, который читает монитор): монитор САМ ведёт ``previous_states`` /
``get_supervision_snapshot()`` (``failed`` получается настоящим «сдался» монитора: ``max_retries: 0``).

Решения тестера (ASSUMPTION; список — в отчёте):
  * окно сбрасывается/истекает по реальным часам (малые ``run_restart_grace_s`` и ``time.sleep``): тесты не
    зависят от того, какие часы (``time.time`` / ``time.monotonic``) использует PM для ``down_since``;
  * текст причин сравнивается точной строкой (ключ ``reason``): «перезапуск cam»,
    «cam: перезапуск не завершён за 0.5 с», «cam: супервизор отказался от перезапуска»; текст конфиг-причины
    сравнивается без обратных кавычек: «cam: run_auto_restart требует enabled: true»;
  * ``system.run.ack`` после аварии берётся «как обычно» (``test_run_ack.py``): ответ ``success`` и состояние
    ``not_ready`` (процесс мёртв); ``run_gate: false`` в этом тесте — остановка в аварии «завершена» сразу;
  * ребёнок-spawn наблюдает ``_run_event`` на старте (``is_set()``); рестарт — настоящий ``restart_process`` PM
    с настоящим ``ProcessRegistry(run_event=...)`` (а не только повторный ``create_and_register``).
"""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from ..core.process_registry import ProcessRegistry
from ..topology.blueprint import ProcessConfig
from .conftest import make_pm
from .test_run_commands import _failure_nodes, _to_running, beat, make_readiness_pm, tick

_THIS = "multiprocess_framework.modules.process_manager_module.tests.test_run_auto_restart"
# backoff_sec огромный: монитор планирует рестарт, но в рамках теста не диспатчит его
_FLAGGED = {"enabled": True, "run_auto_restart": True, "backoff_sec": 600.0}
_RESTART_REASON = "перезапуск cam"


def _pm_with(restart_policy: dict | None, *, grace_s: float | None = None, run_gate: bool = True) -> tuple[Any, Any]:
    cfg: dict[str, Any] = {"class": "pkg.Cam"}
    if restart_policy is not None:
        cfg["restart_policy"] = dict(restart_policy)
    pm, monitor = make_readiness_pm({"cam": cfg}, run_gate=run_gate)
    if grace_s is not None:
        pm.update_config("run_restart_grace_s", grace_s)
    return pm, monitor


def _crash(pm: Any, name: str = "cam") -> None:
    proc = pm._process_registry.get_process_by_name(name)
    proc._alive = False
    proc.exitcode = -9


def _revive(pm: Any, monitor: Any, name: str = "cam") -> None:
    """Процесс вернулся НОВЫМ воплощением (Task 1.7c: оживший старый процесс пометку «перезапускается» не снимает —
    ее снимает heartbeat с ``pid`` нового воплощения): другой pid в реестре и в heartbeat."""
    proc = pm._process_registry.get_process_by_name(name)
    proc._alive = True
    proc.exitcode = None
    proc.pid = 50_000 + (proc.pid or 0) % 1000 + 1
    now = time.time()
    monitor._on_heartbeat_received(
        {
            "sender": name,
            "timestamp": now,
            "pid": proc.pid,
            "readiness": {"ready": True, "reasons": [], "paused": False, "at": now},
        }
    )


def _raw_tick(monitor: Any) -> None:
    """Такт монитора без проверки «нет ошибок»: настоящий «сдался» монитора пишет в ``_log_error`` сам."""
    with monitor._iteration_lock:
        monitor._run_iteration()


def _reasons(pm: Any) -> list[dict]:
    return pm._cmd_system_run_status()["reasons"]


# --------------------------------------------------------------------------- #
# 1. Падение процесса с флагом: running держится, причина «перезапуск»; окно истекло -> fault
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_flagged_process_down_keeps_running_then_fault_when_window_expires() -> None:
    """``running``; процесс с флагом упал -> такт: состояние ``running``, ``run_event`` взведён, в статусе одна
    причина ``out_of_spec``/``liveness`` «перезапуск cam», ``failure`` нет; монитор при этом планирует рестарт по
    per-process политике (``restart_count`` 1). После ``run_restart_grace_s`` (0.5 с) без возвращения -> ``fault``,
    ``run_event`` снят, причина ``failure`` «cam: перезапуск не завершён за 0.5 с»."""
    pm, monitor = _pm_with(_FLAGGED, grace_s=0.5)
    _to_running(pm, monitor)

    _crash(pm)
    _raw_tick(monitor)

    assert pm._run_state == "running"
    assert pm._run_event.is_set() is True
    status = pm._cmd_system_run_status()
    assert status["state"] == "running", status
    assert [(r["node"], r["severity"], r["source"], r["reason"]) for r in status["reasons"]] == [
        ("cam", "out_of_spec", "liveness", _RESTART_REASON)
    ], status
    assert monitor.get_supervision_snapshot()["cam"]["restart_count"] == 1  # политика процесса с флагом цела

    time.sleep(0.8)  # окно 0.5 с истекло, процесс не вернулся
    _raw_tick(monitor)

    assert pm._run_state == "fault"
    assert pm._run_event.is_set() is False
    status = pm._cmd_system_run_status()
    assert status["state"] == "fault", status
    timeouts = [r for r in status["reasons"] if r["reason"] == "cam: перезапуск не завершён за 0.5 с"]
    assert len(timeouts) == 1, status
    assert timeouts[0]["node"] == "cam" and timeouts[0]["severity"] == "failure", status


@pytest.mark.timeout(60)
def test_window_resets_when_process_recovers_between_failures() -> None:
    """``run_restart_grace_s`` 1.5 с: упал -> такт -> 1.0 с -> вернулся (свежий heartbeat) -> такт (причин нет,
    ``running``) -> упал снова -> такт -> 1.0 с -> такт: всё ещё ``running`` (окно считается от второго падения;
    от первого прошло бы ~2.0 с > 1.5 с, и без сброса записи вышел бы ``fault``)."""
    pm, monitor = _pm_with(_FLAGGED, grace_s=1.5)
    _to_running(pm, monitor)

    _crash(pm)
    _raw_tick(monitor)
    assert [r["reason"] for r in _reasons(pm)] == [_RESTART_REASON]
    time.sleep(1.0)

    _revive(pm, monitor)
    _raw_tick(monitor)
    assert pm._run_state == "running"
    assert _reasons(pm) == [], _reasons(pm)  # failure у процесса нет: причины ушли, запись окна снята

    _crash(pm)
    _raw_tick(monitor)
    assert pm._run_state == "running"
    time.sleep(1.0)
    _raw_tick(monitor)

    assert pm._run_state == "running", pm._cmd_system_run_status()
    assert [r["reason"] for r in _reasons(pm)] == [_RESTART_REASON]


# --------------------------------------------------------------------------- #
# 2. Супервизор отказался (настоящий снимок монитора) -> fault -> ack как обычно
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_supervisor_gave_up_goes_fault_at_once_then_ack() -> None:
    """Процесс с флагом упал, монитор исчерпал попытки (``max_retries: 0``): в настоящем снимке
    ``status == "failed"``. Окно 30 с (умолчание) далеко не истекло, но такт -> ``fault`` с причиной ``failure``
    «cam: супервизор отказался от перезапуска» в ``last_fault``; ``system.run.ack`` проходит: ``success``,
    ``not_ready`` (процесс мёртв)."""
    pm, monitor = _pm_with({**_FLAGGED, "max_retries": 0}, run_gate=False)
    _to_running(pm, monitor)

    _crash(pm)
    for _ in range(3):  # такт читает снимок ДО обработки смерти монитором: «сдался» виден со следующего такта
        _raw_tick(monitor)
        if pm._run_state == "fault":
            break
    snapshot = monitor.get_supervision_snapshot()["cam"]
    assert snapshot["status"] == "failed", snapshot  # предусловие стенда: настоящий отказ супервизора

    assert pm._run_state == "fault", pm._cmd_system_run_status()
    status = pm._cmd_system_run_status()
    gave_up = [r for r in status["last_fault"]["reasons"] if r["reason"] == "cam: супервизор отказался от перезапуска"]
    assert len(gave_up) == 1, status
    assert gave_up[0]["node"] == "cam" and gave_up[0]["severity"] == "failure", status

    reply = pm._cmd_system_run_ack()

    assert reply["success"] is True, reply
    assert reply["state"] == "not_ready", reply


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "restart_policy", [{"enabled": True, "backoff_sec": 600.0}, None], ids=["enabled", "no-policy"]
)
def test_unflagged_process_down_goes_fault_at_once(restart_policy: dict | None) -> None:
    """Охранный (зелёный до реализации): тот же процесс БЕЗ флага (с политикой ``enabled`` и вовсе без политики),
    упавший в ``running``, -> первый же такт ``fault`` с ``failure`` «процесс не жив»; события нет."""
    pm, monitor = _pm_with(restart_policy)
    _to_running(pm, monitor)

    _crash(pm)
    _raw_tick(monitor)

    assert pm._run_state == "fault"
    assert pm._run_event.is_set() is False
    status = pm._cmd_system_run_status()
    assert _failure_nodes(status["reasons"]) == ["cam"], status
    assert status["reasons"][0]["reason"] == "процесс не жив", status


# --------------------------------------------------------------------------- #
# 3. Флаг без enabled: true — конфиг-failure, система не готова, START отказан
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("restart_policy", "refused"),
    [
        pytest.param({"run_auto_restart": True}, True, id="flag-without-enabled"),
        pytest.param({"enabled": False, "run_auto_restart": True}, True, id="flag-with-enabled-false"),
        # охранные (зелёные до реализации): корректный флаг и выключенный флаг START не мешают
        pytest.param({"enabled": True, "run_auto_restart": True}, False, id="guard-flag-with-enabled"),
        pytest.param({"run_auto_restart": False}, False, id="guard-flag-false-without-enabled"),
    ],
)
def test_flag_requires_enabled(restart_policy: dict, refused: bool) -> None:
    """Здоровый процесс с ``run_auto_restart: true`` без ``enabled: true`` -> такт -> ``not_ready``; причина
    ``failure``/``config`` по узлу «cam: run_auto_restart требует enabled: true»; START отказан ``not_ready`` с
    этой причиной, ``run_event`` не взведён. Флаг с ``enabled: true`` и ``run_auto_restart: false`` -> ``ready``, START
    проходит."""
    pm, monitor = _pm_with(restart_policy)
    beat(monitor, "cam")
    tick(pm, monitor)

    reply = pm._cmd_system_run_start()

    if not refused:
        assert pm._cmd_system_run_status()["reasons"] == []
        assert reply == {"success": True, "state": "running"}
        return
    assert pm._cmd_system_run_status()["state"] == "not_ready"
    assert reply["success"] is False and reply["error"] == "not_ready", reply
    assert pm._run_event.is_set() is False
    config_reasons = [r for r in reply["reasons"] if r["source"] == "config"]
    assert len(config_reasons) == 1, reply
    assert config_reasons[0]["node"] == "cam" and config_reasons[0]["severity"] == "failure", reply
    assert config_reasons[0]["reason"].replace("`", "") == "cam: run_auto_restart требует enabled: true", reply
    assert _failure_nodes(reply["reasons"]) == ["cam"], reply


# --------------------------------------------------------------------------- #
# 4. Флаг доходит до _process_configs настоящей цепочкой (охранный: контейнер restart_policy — свободный dict)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("restart_policy", "flag_on"),
    [({"enabled": True, "run_auto_restart": True}, True), ({"enabled": True}, False)],
    ids=["flag-true", "flag-absent-default-off"],
)
def test_flag_reaches_process_configs_through_real_chain(restart_policy: dict, flag_on: bool) -> None:
    """``ProcessConfig(restart_policy=...)`` -> ``as_generic_config().build()`` -> сид создания PM
    (``_topology_create``) -> ``_process_configs["cam"]["restart_policy"]``: флаг не потерян; не заданный флаг
    ничего не включает (умолчание ``False``)."""
    _name, proc_dict = ProcessConfig(process_name="cam", restart_policy=restart_policy).as_generic_config().build()
    pm = make_pm()

    assert pm._topology_create("cam", proc_dict) is True

    stored = pm._process_configs["cam"]["restart_policy"]
    assert stored["enabled"] is True, stored
    assert bool(stored.get("run_auto_restart", False)) is flag_on, stored


# --------------------------------------------------------------------------- #
# 5. Настоящий spawn: ребёнок после рестарта наследует взведённый run_event (охранный)
# --------------------------------------------------------------------------- #


class ArmedChild:
    """Ребёнок: на старте пишет в ``marks.txt`` свой pid и то, взведён ли ``_run_event`` (атрибут ставит runner)."""

    def __init__(self, name: str, shared_resources, config) -> None:
        self.name = name
        self._dir = Path(os.environ["RUN_EVT_DIR"])
        self._own_ready = None

    def initialize(self) -> bool:
        return True

    def attach_ready_event(self, event) -> None:
        self._own_ready = event

    def run(self) -> None:
        ev = getattr(self, "_run_event", None)
        with open(self._dir / "marks.txt", "a", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()} armed={ev is not None and ev.is_set()}\n")
        if self._own_ready is not None:
            self._own_ready.set()

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


@pytest.mark.timeout(120)
def test_restarted_child_inherits_armed_run_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Настоящий spawn: ``run_event`` взведён, первый ребёнок видит его взведённым; ``restart_process`` PM
    пересоздаёт ребёнка (другой pid) — и второй ребёнок на старте видит ``run_event`` взведённым."""
    monkeypatch.setenv("RUN_EVT_DIR", str(tmp_path))
    box: dict[str, Any] = {}

    def scenario() -> None:
        run_event = multiprocessing.Event()
        run_event.set()  # система в работе
        pm = make_pm()
        registry = ProcessRegistry(logger=None, run_event=run_event)
        pm._process_registry = registry
        process = pm.create_process("armed_child", f"{_THIS}.ArmedChild", {}, "normal")
        try:
            assert process is not None, "create_process вернул None"
            process.start()
            assert registry.get_ready_event("armed_child").wait(30.0), "первый ребёнок не объявил готовность"
            assert pm.restart_process("armed_child") is True
            assert registry.get_ready_event("armed_child").wait(30.0), "второй ребёнок не объявил готовность"
        except BaseException as exc:  # noqa: BLE001 — в поток теста
            box["exc"] = exc
        finally:
            registry.stop_all(timeout=5.0)

    thread = threading.Thread(target=scenario, daemon=True, name="auto-restart-spawn")
    thread.start()
    thread.join(100.0)
    assert not thread.is_alive(), "сценарий завис дольше 100 с"
    if "exc" in box:
        raise box["exc"]

    marks = (tmp_path / "marks.txt").read_text(encoding="utf-8").splitlines()
    assert len(marks) == 2, marks
    assert [m.split()[1] for m in marks] == ["armed=True", "armed=True"], marks
    assert marks[0].split()[0] != marks[1].split()[0], marks  # действительно другой процесс
