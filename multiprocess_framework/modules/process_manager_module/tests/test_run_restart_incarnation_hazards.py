# -*- coding: utf-8 -*-
"""Task 1.7c (system-run-state) — hazard-тесты воплощения процесса (автор реализации).

Слепые приёмочные — ``test_run_restart_incarnation.py`` (PM + монитор), ``test_run_state_restarting.py`` (чистая
``evaluate``), ``process_module/tests/test_heartbeat_pid.py``. Здесь — то, чего они не фиксируют: гонка heartbeat
старого/нового pid с исполнением рестарта, «перезапускается» не залипает (повторное решение, ``forget_process``,
каскад), ручной ``process.restart`` во время запланированного, сквозной тест с настоящим spawn и pid, heartbeat без
``pid`` / с негодным ``pid`` в перезапуске, ``recovered`` ровно один раз, остановка в аварии не ждёт приговорённого.

Обвязка — как у слепого файла (``make_readiness_pm``, двойник реестра, такт ``monitor._run_iteration()``).
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
from ..core.restart_policy import RestartPolicy
from ..monitor.process_monitor import ProcessMonitor
from .conftest import make_pm
from .test_run_commands import make_readiness_pm
from .test_run_restart_incarnation import (
    _NEW_PID,
    _OLD_PID,
    _beat,
    _booted,
    _decided,
    _executed,
    _manual_restart,
    _pm,
    _raw_tick,
    _spy_events,
)

_JOIN_S = 30.0
_THIS = "multiprocess_framework.modules.process_manager_module.tests.test_run_restart_incarnation_hazards"


def _restarting(monitor: Any) -> frozenset[str]:
    return monitor.readiness_view()[1]


# --------------------------------------------------------------------------- #
# 1. Гонка: heartbeat старого pid против исполнения рестарта
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_old_pid_heartbeat_race_never_lifts_restarting_new_pid_lifts() -> None:
    """Потоки шлют heartbeat СТАРОГО pid (свежий лист) без остановки; пока реестр держит старое воплощение, пометка
    не снимается ни разу и листа нет; главный поток подменяет реестр на новое воплощение и шлёт heartbeat нового pid
    — пометка снята, лист принят. Потоки с дедлайном join."""
    pm, monitor = _pm(backoff=0.3)
    _booted(pm, monitor)
    _decided(pm, monitor)
    stop = threading.Event()
    swapping = threading.Event()  # взводится ДО подмены реестра
    seen_lifted_early: list[bool] = []

    def old_beats() -> None:
        while not stop.is_set():
            _beat(monitor, pid=_OLD_PID)
            lifted = "cam" not in _restarting(monitor)  # состояние читается ДО флага: подъём возможен лишь после него
            if lifted and not swapping.is_set():
                seen_lifted_early.append(True)

    threads = [threading.Thread(target=old_beats, daemon=True, name=f"old-beat-{i}") for i in range(4)]
    for thread in threads:
        thread.start()
    try:
        time.sleep(0.2)  # старые heartbeat идут, реестр держит старое воплощение
        assert "cam" in _restarting(monitor)
        assert "cam" not in monitor.readiness_snapshot()
        swapping.set()
        _executed(pm, monitor)  # реестр -> _NEW_PID, пока потоки шлют старые heartbeat
        deadline = time.monotonic() + 10.0
        while "cam" in _restarting(monitor) and time.monotonic() < deadline:
            _beat(monitor, pid=_NEW_PID)
    finally:
        stop.set()
        for thread in threads:
            thread.join(_JOIN_S)
            assert not thread.is_alive(), f"поток {thread.name} завис"

    assert seen_lifted_early == [], "старый pid снял пометку"
    assert "cam" not in _restarting(monitor)
    assert "cam" in monitor.readiness_snapshot()


# --------------------------------------------------------------------------- #
# 2. «Перезапускается» не залипает: повторное решение, forget_process, каскад
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("how", ["repeat-decision", "forget-process", "cascade"])
def test_restarting_does_not_stick(how: str) -> None:
    """Повторное решение (после исполнения, как watchdog H3) перезапоминает pid: heartbeat уже НЕ нового воплощения
    не снимает, следующего — снимает. ``forget_process`` (apply / удаление) стирает пометку, и имя принимает лист.
    Каскадный рестарт ставит пометку члену и снимается heartbeat нового воплощения."""
    pm, monitor = _pm(backoff=0.3)
    _booted(pm, monitor)
    if how == "cascade":
        monitor._resolve_restart_set = lambda *_a, **_k: ["cam"]  # член группы: решение каскада принято
        policy = RestartPolicy(enabled=True, strategy="one_for_all", backoff_sec=0.0)
        monitor._cascade_restart("trigger", policy, 0.0, time.monotonic(), set())
        assert "cam" in _restarting(monitor)
        pm._process_registry.get_process_by_name("cam").pid = _NEW_PID  # исполнение
        _beat(monitor, pid=_NEW_PID)
        assert _restarting(monitor) == frozenset()
        return
    _decided(pm, monitor)
    _executed(pm, monitor)  # реестр держит _NEW_PID
    if how == "forget-process":
        monitor.forget_process("cam")
        assert _restarting(monitor) == frozenset()
        _beat(monitor, pid=_NEW_PID)  # имя переиспользуется воплощением реестра: лист принимается
        assert "cam" in monitor.readiness_snapshot()
        return
    monitor.mark_restarting("cam")  # повторное решение: убить предстоит и воплощение _NEW_PID
    _beat(monitor, pid=_NEW_PID)
    assert "cam" in _restarting(monitor), "heartbeat воплощения, которое убьёт повторный рестарт, снял пометку"
    pm._process_registry.get_process_by_name("cam").pid = _NEW_PID + 1  # исполнение повторного рестарта
    _beat(monitor, pid=_NEW_PID + 1)
    assert _restarting(monitor) == frozenset()


# --------------------------------------------------------------------------- #
# 3. Ручной process.restart во время запланированного авто-рестарта
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_manual_restart_during_scheduled_auto_restart_rearms_each_restart() -> None:
    """Решение супервизора (backoff не истёк) -> ручной ``process.restart`` -> heartbeat нового pid снимает пометку
    (``ready``). Затем исполняется запланированный рестарт: команда ``process.restart`` ЗАНОВО ставит пометку
    (``restart_process`` помечает на входе), и её снимает только heartbeat воплощения этого рестарта."""
    pm, monitor = _pm()
    _booted(pm, monitor)
    _decided(pm, monitor)
    _manual_restart(pm)
    _beat(monitor, pid=_OLD_PID)
    assert "cam" in _restarting(monitor)
    _beat(monitor, pid=_NEW_PID)
    _raw_tick(monitor)
    assert pm._run_state == "ready", pm._cmd_system_run_status()

    registry = pm._process_registry
    registry._next_process_factory["cam"] = type(registry.get_process_by_name("cam"))("cam", alive=False)
    reply = pm._cmd_process_restart({"process_name": "cam"})  # исполнение запланированного рестарта

    assert reply["success"] is True, reply
    assert "cam" in _restarting(monitor)
    _raw_tick(monitor)
    assert pm._run_state == "not_ready", pm._cmd_system_run_status()


# --------------------------------------------------------------------------- #
# 4. Сквозной: настоящий spawn, настоящие pid
# --------------------------------------------------------------------------- #


class PidChild:
    """Ребёнок: на старте пишет свой pid в ``marks.txt`` (``pid=<n>``)."""

    def __init__(self, name: str, shared_resources, config) -> None:
        self.name = name
        self._dir = Path(os.environ["INCARNATION_DIR"])
        self._own_ready = None

    def initialize(self) -> bool:
        return True

    def attach_ready_event(self, event) -> None:
        self._own_ready = event

    def run(self) -> None:
        with open(self._dir / "marks.txt", "a", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()}\n")
        if self._own_ready is not None:
            self._own_ready.set()

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


@pytest.mark.timeout(120)
def test_real_spawn_restart_lifts_restarting_only_by_new_real_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Настоящий spawn: ``restart_process`` пересоздаёт ребёнка (другой pid ОС). До рестарта процесс помечен,
    heartbeat со СТАРЫМ pid пометку не снимает; heartbeat с pid нового ребёнка (его же pid из ``marks.txt`` и из
    реестра) — снимает, лист принят."""
    monkeypatch.setenv("INCARNATION_DIR", str(tmp_path))
    box: dict[str, Any] = {}

    def scenario() -> None:
        pm = make_pm()
        registry = ProcessRegistry(logger=None, run_event=multiprocessing.Event())
        pm._process_registry = registry
        monitor = ProcessMonitor(pm, poll_interval=0.01, heartbeat_timeout=15.0)
        pm._process_monitor = monitor
        process = pm.create_process("pid_child", f"{_THIS}.PidChild", {}, "normal")
        try:
            assert process is not None
            process.start()
            assert registry.get_ready_event("pid_child").wait(30.0), "первый ребёнок не объявил готовность"
            box["old"] = registry.get_process_by_name("pid_child").pid
            assert pm.restart_process("pid_child") is True  # помечает на входе и пересоздаёт ребёнка
            assert registry.get_ready_event("pid_child").wait(30.0), "второй ребёнок не объявил готовность"
            box["new"] = registry.get_process_by_name("pid_child").pid
            leaf = {"ready": True, "reasons": [], "paused": False, "at": time.time()}
            monitor._on_heartbeat_received({"sender": "pid_child", "pid": box["old"], "readiness": leaf})
            box["after_old"] = (_restarting(monitor), dict(monitor.readiness_snapshot()))
            monitor._on_heartbeat_received({"sender": "pid_child", "pid": box["new"], "readiness": leaf})
            box["after_new"] = (_restarting(monitor), dict(monitor.readiness_snapshot()))
        except BaseException as exc:  # noqa: BLE001 — в поток теста
            box["exc"] = exc
        finally:
            registry.stop_all(timeout=5.0)

    thread = threading.Thread(target=scenario, daemon=True, name="incarnation-spawn")
    thread.start()
    thread.join(100.0)
    assert not thread.is_alive(), "сценарий завис дольше 100 с"
    if "exc" in box:
        raise box["exc"]

    marks = (tmp_path / "marks.txt").read_text(encoding="utf-8").split()
    assert marks == [str(box["old"]), str(box["new"])], (marks, box)
    assert box["old"] != box["new"]
    assert box["after_old"] == (frozenset({"pid_child"}), {}), box["after_old"]
    assert box["after_new"][0] == frozenset() and "pid_child" in box["after_new"][1], box["after_new"]


# --------------------------------------------------------------------------- #
# 5. Heartbeat без pid / с негодным pid в перезапуске
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("pid", [None, _OLD_PID, True, "41002", 41002.0], ids=["no-pid", "old", "bool", "str", "float"])
def test_heartbeat_without_valid_new_pid_does_not_lift_restarting(pid: Any) -> None:
    """Реестр держит новое воплощение (41002). Heartbeat без ``pid``, со старым, ``True``, строкой или дробным
    числом пометку не снимает и лист не кладёт; целый 41002 — снимает."""
    pm, monitor = _pm(backoff=0.3)
    _booted(pm, monitor)
    _decided(pm, monitor)
    _executed(pm, monitor)

    _beat(monitor, pid=pid)

    assert "cam" in _restarting(monitor)
    assert "cam" not in monitor.readiness_snapshot()
    _beat(monitor, pid=_NEW_PID)
    assert "cam" not in _restarting(monitor)


# --------------------------------------------------------------------------- #
# 6. recovered ровно один раз; после снятия heartbeat без pid принимается (совместимость)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_recovered_once_and_pidless_heartbeat_accepted_after_lift() -> None:
    """Старые heartbeat до и после исполнения и ВСЕ такты — ``recovered`` нет; много heartbeat нового pid и тактов —
    ровно одно ``recovered``; после снятия heartbeat ребёнка без ``pid`` принимается как раньше."""
    pm, monitor = _pm(backoff=0.3)
    _booted(pm, monitor)
    events = _spy_events(monitor)
    _decided(pm, monitor)
    for _ in range(3):
        _beat(monitor, pid=_OLD_PID)
        _raw_tick(monitor)
    _executed(pm, monitor)
    _beat(monitor, pid=_OLD_PID)
    _raw_tick(monitor)
    assert ("cam", "recovered") not in events, events

    for _ in range(4):
        _beat(monitor, pid=_NEW_PID)
        _raw_tick(monitor)
    assert events.count(("cam", "recovered")) == 1, events

    late_at = _beat(monitor, pid=None)
    assert monitor.readiness_snapshot()["cam"]["at"] == late_at


# --------------------------------------------------------------------------- #
# 7. Остановка в аварии не ждёт paused от приговорённого
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_does_not_wait_paused_from_restarting_process() -> None:
    """Живой процесс, помеченный «перезапускается» (его лист не принимается), в ожидание ``paused`` остановки не
    попадает; без пометки тот же процесс (лист не ``paused``) — ждётся."""
    pm, monitor = _pm()
    _booted(pm, monitor)
    assert pm._paused_pending() == ["cam"]  # лист не paused -> ждём

    monitor.mark_restarting("cam")

    assert pm._paused_pending() == []


# --------------------------------------------------------------------------- #
# 8. PM-уровень: restarting доходит до оценки; процесс вне топологии не оставляет записи
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_restarting_reaches_evaluation_and_gone_process_leaves_no_record() -> None:
    """Пометка монитора видна оценке PM (причина «перезапускается супервизором» по узлу); процесс, снятый из
    топологии (cleanup -> ``forget_process``), не оставляет записи в ``readiness_view``."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}, "aux": {"class": "pkg.Aux"}})
    monitor.mark_restarting("cam")
    monitor.mark_restarting("aux")

    ready, reasons = pm._evaluate_run_readiness()

    assert ready is False
    assert sorted((r["node"], r["reason"]) for r in reasons) == [
        ("aux", "aux: перезапускается супервизором"),
        ("cam", "cam: перезапускается супервизором"),
    ]
    monitor.forget_process("aux")
    leaves, restarting = monitor.readiness_view()
    assert restarting == frozenset({"cam"}) and "aux" not in leaves


# --------------------------------------------------------------------------- #
# 9. Идентичность проверяется всегда: поздний heartbeat старого pid после снятия пометки лист не перетирает
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_late_old_pid_heartbeat_after_lift_does_not_overwrite_new_leaf() -> None:
    """Пометка снята heartbeat нового pid (лист нового воплощения принят); затем приходит поздний heartbeat СТАРОГО
    pid со «свежим» листом другого содержания: лист нового не перетёрт, но heartbeat учтён как жизнь
    (``_last_heartbeat`` обновлён); heartbeat без ``pid`` и с pid реестра по-прежнему принимаются."""
    pm, monitor = _pm(backoff=0.3)
    _booted(pm, monitor)
    _decided(pm, monitor)
    _executed(pm, monitor)
    new_at = _beat(monitor, pid=_NEW_PID)
    assert "cam" not in _restarting(monitor)
    monitor._last_heartbeat.pop("cam", None)

    _beat(monitor, pid=_OLD_PID, at_age=-5.0)  # лист «из будущего»: перетёр бы лист нового, будь он принят

    assert monitor.readiness_snapshot()["cam"]["at"] == new_at
    assert monitor._last_heartbeat.get("cam") is not None  # heartbeat старого воплощения — всё же жизнь
    fresh_at = _beat(monitor, pid=None)  # совместимость: без pid принимается
    assert monitor.readiness_snapshot()["cam"]["at"] == fresh_at
    fresher_at = _beat(monitor, pid=_NEW_PID)  # pid реестра принимается
    assert monitor.readiness_snapshot()["cam"]["at"] == fresher_at
