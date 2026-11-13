# -*- coding: utf-8 -*-
"""Task 1.8b (system-run-state) — слепые приёмочные тесты супервизора: новое воплощение процесса, повторный рестарт.

Контракт (из текста Task, ACCEPTANCE 1-6; interface.py нет): авто-рестарт супервизора работает на КАЖДОЕ падение
и зависание процесса, а не один раз за жизнь процесса; одна поломка тратит ровно одну попытку из ``max_restarts``
(``max_retries`` политики); статус восстановленного воплощения — ``running``; ``failed`` достижим, и run-state при
флаге ``run_auto_restart`` уходит в ``fault`` «сдался» раньше окна ``run_restart_grace_s``.

Ключевая ловушка, ради которой файл написан: в остальных тестах PM реестр состояний процессов —
``MagicMock`` (``MockSharedResources.process_state_registry``), поэтому статус «по имени» там не виден.
Здесь ``pm.shared_resources`` — НАСТОЯЩИЙ ``SharedResourcesManager`` с настоящим ``ProcessStateRegistry``;
``restart_process`` PM и ``register_process`` из него — настоящие.

Что настоящее: ``ProcessManagerProcess`` (``make_readiness_pm``), ``ProcessMonitor`` (такт ``_run_iteration``),
``SharedResourcesManager`` / ``ProcessStateRegistry`` / очереди SRM, ``pm.restart_process`` (через настоящий
обработчик ``pm._cmd_process_restart`` на ту самую команду ``process.restart``, которую монитор отправил).
Двойники: процесс ОС (``is_alive`` / ``exitcode`` / ``pid``; смерть при стопе — ``exitcode`` по ТЗ: 0 или -15),
реестр OS-процессов (наследник ``MockProcessRegistry``: стоп ``stop_one`` убивает двойника и в этот момент даёт
монитору такт — как поток монитора в продакшене), IPC-отправка PM (``communication`` — ``MagicMock``,
считаются отправленные ``process.restart``).

Решения тестера (ASSUMPTION; список — в отчёте):
  * строки событий — ``(event, attempt)`` из ``monitor._emit_supervisor_event``; попытка — ``"k/N"`` с ``N`` =
    ``max_retries`` политики процесса;
  * «статус по такту» читается тремя путями сразу: ``monitor.previous_states``, ``supervision.status`` PM
    (``_cmd_supervision_status``) и ``monitor.get_supervision_snapshot()``;
  * падение — ``exitcode = -9`` (``kill -9``), зависание — heartbeat с меткой старше ``heartbeat_timeout`` (15 с);
  * backoff рестарта 0.05 с; рестарт, отправленный монитором, исполняет тест: берёт ``data`` отправленного
    сообщения и зовёт ``pm._cmd_process_restart`` (то, что делает исполнитель ``pm-lifecycle`` PM).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest

from ...shared_resources_module.core.shared_resources_manager import SharedResourcesManager
from .conftest import MockProcess, MockProcessRegistry
from .test_run_commands import make_readiness_pm

_NAME = "cam"
_MAX_RETRIES = 3
_BACKOFF_S = 0.05
_STALE_HB_S = 16.0  # возраст метки heartbeat: больше heartbeat_timeout (15 с) -> unresponsive
_DEADLINE_S = 90  # потолок сценария в daemon-потоке; тест не виснет
_WAIT_S = 5.0  # сколько ждём, что монитор отправит рестарт


# --------------------------------------------------------------------------- #
# Двойники: процесс ОС и реестр OS-процессов
# --------------------------------------------------------------------------- #


class _OsProc(MockProcess):
    """Двойник процесса ОС: ``pid`` назначается при ``start`` (новое воплощение — новый pid), ``exitcode``."""

    def __init__(self, name: str, pids: list[int]) -> None:
        super().__init__(name, alive=False)
        self._pids = pids
        self.exitcode: int | None = None

    def start(self) -> None:
        self._alive = True
        self._started = True
        self.exitcode = None
        self.pid = self._pids[-1] + 1
        self._pids.append(self.pid)

    def die(self, exitcode: int) -> None:
        self._alive = False
        self.exitcode = exitcode


class _Registry(MockProcessRegistry):
    """Реестр OS-процессов: рождает ``_OsProc``; стоп убивает старое воплощение с ``stop_exitcode`` ОС."""

    def __init__(self, pids: list[int]) -> None:
        super().__init__()
        self._pids = pids
        self.stop_exitcode: int = -15
        #: вызывается ПОСЛЕ смерти старого воплощения, пока оно ещё в реестре (поток монитора идёт параллельно)
        self.during_stop: Callable[[], None] | None = None

    def create_and_register(self, name: str, class_path: str, config: dict | None = None, priority: str = "normal"):
        proc = _OsProc(name, self._pids)
        self._processes[name] = proc
        return proc

    def stop_one(self, name: str, timeout: float = 5.0, *, mark_reader_gone: bool = True) -> bool:
        proc = self._processes.get(name)
        if proc is None:
            return True
        if proc.is_alive():
            proc.die(self.stop_exitcode)
        if self.during_stop is not None:
            self.during_stop()
        return True


# --------------------------------------------------------------------------- #
# Стенд
# --------------------------------------------------------------------------- #


class _Rig:
    """PM + настоящий монитор + настоящий SRM/PSR; ``cam`` с политикой ``enabled`` и ``max_retries`` = 3."""

    def __init__(self, *, run_auto_restart: bool = False, max_retries: int = _MAX_RETRIES) -> None:
        policy = {
            "enabled": True,
            "max_retries": max_retries,
            "backoff_sec": _BACKOFF_S,
            "window_sec": 3600.0,
            "run_auto_restart": run_auto_restart,
        }
        cfg = {"class": "pkg.Cam", "restart_policy": policy}
        self.pm, self.monitor = make_readiness_pm({_NAME: cfg})
        pm = self.pm
        # Настоящий реестр состояний: SRM создаёт PSR, очереди и события процесса.
        self.srm = SharedResourcesManager(manager_name="rig_srm")
        assert self.srm.initialize() is True
        assert self.srm.register_process(_NAME, dict(cfg)) is True
        pm.shared_resources = self.srm
        # Реестр OS-процессов: первое воплощение уже запущено (pid 41001).
        self.pids: list[int] = [41000]
        self.registry = _Registry(self.pids)
        first = self.registry.create_and_register(_NAME, "pkg.Cam")
        first.start()
        pm._process_registry = self.registry
        # События супервизора.
        self.events: list[tuple[str, str | None]] = []
        original = self.monitor._emit_supervisor_event

        def spy(process_name: str, event: str, **kwargs: Any) -> None:
            if process_name == _NAME:
                self.events.append((event, kwargs.get("attempt")))
            original(process_name, event, **kwargs)

        self.monitor._emit_supervisor_event = spy
        self._executed = 0

    # --- воплощения ---

    @property
    def proc(self) -> _OsProc:
        return self.registry.get_process_by_name(_NAME)

    @property
    def pid(self) -> int:
        return self.proc.pid

    # --- сигналы ---

    def beat(self, *, ts_age: float = 0.0, pid: int | None = None) -> None:
        """Heartbeat ``cam`` (готов, лист свежий); ``ts_age`` — возраст метки времени сообщения."""
        now = time.time()
        self.monitor._on_heartbeat_received(
            {
                "sender": _NAME,
                "timestamp": now - ts_age,
                "pid": self.pid if pid is None else pid,
                "status": "running",
                "readiness": {"ready": True, "reasons": [], "paused": False, "at": now},
            }
        )

    def tick(self) -> None:
        with self.monitor._iteration_lock:
            self.monitor._run_iteration()

    def ticks(self, n: int) -> None:
        for _ in range(n):
            self.tick()

    def crash(self) -> None:
        """``kill -9``: процесс мёртв, ``exitcode`` -9."""
        self.proc.die(-9)

    def hang(self) -> None:
        """``kill -STOP``: процесс жив, heartbeat с метки старше ``heartbeat_timeout``."""
        self.beat(ts_age=_STALE_HB_S)

    # --- наблюдаемое ---

    def sends(self) -> list[dict]:
        """Отправленные монитором команды ``process.restart`` (IPC в PM)."""
        out = []
        for call in self.pm.communication.send_message.call_args_list:
            msg = call.args[1]
            if isinstance(msg, dict) and msg.get("command") == "process.restart":
                out.append(msg)
        return out

    def attempts(self) -> list[str | None]:
        """Строки попыток событий ``restarting``: ``["1/3", "2/3", ...]``."""
        return [attempt for event, attempt in self.events if event == "restarting"]

    def statuses(self) -> dict[str, Any]:
        """Статус ``cam`` тремя путями: ``previous_states``, ``supervision.status`` PM, снимок монитора."""
        prev = (self.monitor.previous_states.get(_NAME) or {}).get("status")
        sup = self.pm._cmd_supervision_status()["processes"][_NAME]["status"]
        snap = self.monitor.get_supervision_snapshot()[_NAME]["status"]
        return {"previous_states": prev, "supervision_status": sup, "snapshot": snap}

    # --- шаги сценария ---

    def boot(self) -> None:
        """Первое воплощение отчиталось -> такты -> ``running`` (предусловие стенда, не предмет проверки)."""
        self.beat()
        self.ticks(2)
        assert self.statuses() == {
            "previous_states": "running",
            "supervision_status": "running",
            "snapshot": "running",
        }, f"предусловие стенда: boot не довёл cam до running: {self.statuses()}"

    def wait_sends(self, n: int) -> None:
        """Такты, пока монитор не отправит ``n``-й ``process.restart`` (backoff мал); без отправки — тест красный."""
        deadline = time.monotonic() + _WAIT_S
        while len(self.sends()) < n and time.monotonic() < deadline:
            time.sleep(_BACKOFF_S)
            self.tick()

    def execute_restarts(self) -> None:
        """Исполнитель PM: отправленные, но ещё не исполненные ``process.restart`` -> ``pm._cmd_process_restart``."""
        sent = self.sends()
        while self._executed < len(sent):
            reply = self.pm._cmd_process_restart(sent[self._executed]["data"])
            self._executed += 1
            assert reply["success"] is True, f"предусловие стенда: restart_process не исполнен: {reply}"

    def monitor_runs_during_stop(self, n_ticks: int = 3) -> None:
        """Пока PM стопит старое воплощение, поток монитора идёт параллельно: такты между смертью и снятием."""
        self.registry.during_stop = lambda: self.ticks(n_ticks)


def _bounded(scenario: Callable[[], None], deadline_s: float = _DEADLINE_S) -> None:
    """Сценарий в daemon-потоке с join-дедлайном: зависший вызов — красный тест, а не зависший прогон."""
    box: dict[str, BaseException] = {}

    def run() -> None:
        try:
            scenario()
        except BaseException as exc:  # noqa: BLE001 — в поток теста
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True, name="supervisor-restart-scenario")
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"сценарий завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]


# --------------------------------------------------------------------------- #
# 1-2. Каждое падение и каждое зависание = рестарт; счётчик растёт
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_each_crash_triggers_restart_with_growing_counter() -> None:
    """ACCEPTANCE 1: падение -> рестарт 1/3 -> воплощение живёт (heartbeat) -> второе падение -> рестарт 2/3:
    события ``restarting`` ровно ``["1/3", "2/3"]``, ``process.restart`` отправлено ровно 2 раза, в окне 2 рестарта."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()

        rig.crash()
        rig.wait_sends(1)
        assert len(rig.sends()) == 1, f"первое падение: process.restart не отправлен; события {rig.events}"
        rig.execute_restarts()
        assert rig.pid == 41002, "предусловие стенда: рестарт не создал новое воплощение"
        rig.beat()
        rig.ticks(2)

        rig.crash()  # второе падение ОДНОГО И ТОГО ЖЕ процесса уже нового воплощения
        rig.wait_sends(2)

        assert len(rig.sends()) == 2, f"второе падение пропущено: sends={len(rig.sends())}; события {rig.events}"
        assert rig.attempts() == ["1/3", "2/3"], rig.events
        assert rig.monitor.get_supervision_snapshot()[_NAME]["restart_count"] == 2

    _bounded(scenario)


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_each_hang_triggers_restart_with_growing_counter() -> None:
    """ACCEPTANCE 2: зависание (``unresponsive``) -> рестарт 1/3 -> воплощение живёт -> снова зависание -> рестарт
    2/3: события ``restarting`` ровно ``["1/3", "2/3"]``, ``process.restart`` ровно 2 раза."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()

        rig.hang()
        rig.wait_sends(1)
        assert len(rig.sends()) == 1, f"первое зависание: process.restart не отправлен; события {rig.events}"
        rig.execute_restarts()
        assert rig.pid == 41002, "предусловие стенда: рестарт не создал новое воплощение"
        rig.beat()
        rig.ticks(2)

        rig.hang()  # второе зависание нового воплощения
        rig.wait_sends(2)

        assert len(rig.sends()) == 2, f"второе зависание пропущено: sends={len(rig.sends())}; события {rig.events}"
        assert rig.attempts() == ["1/3", "2/3"], rig.events
        assert rig.monitor.get_supervision_snapshot()[_NAME]["restart_count"] == 2

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# 3. Нет мигания: статус восстановленного воплощения — running на каждом такте
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
@pytest.mark.parametrize("failure", ["crash", "hang"])
def test_recovered_incarnation_is_running_on_every_tick(failure: str) -> None:
    """ACCEPTANCE 3: после рестарта и heartbeat статус (``previous_states``, ``supervision.status`` PM, снимок
    монитора) — ``running`` на 6 подряд тактах (heartbeat живого процесса приходит каждый такт); без мигания
    ``crashed`` / ``unresponsive``."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        rig.crash() if failure == "crash" else rig.hang()
        rig.wait_sends(1)
        rig.execute_restarts()
        assert rig.pid == 41002, "предусловие стенда: рестарт не создал новое воплощение"

        seen = []
        for _ in range(6):
            rig.beat()
            rig.tick()
            seen.append(rig.statuses())

        running = {"previous_states": "running", "supervision_status": "running", "snapshot": "running"}
        assert seen == [running] * 6, seen

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# 4. Смерть заменяемого воплощения от SIGTERM во время стопа рестарта — не новое падение
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_replaced_incarnation_dying_of_sigterm_does_not_cause_second_restart() -> None:
    """ACCEPTANCE 4: процесс ``unresponsive``, монитор отправил ``process.restart``; PM стопит старое воплощение, оно
    умирает от SIGTERM (``exitcode`` -15) и монитор в этот момент делает такты -> ровно один рестарт: ``sends == 1``
    (и после ожидания, превышающего backoff), событие ``restarting`` одно (``"1/3"``), в окне 1 рестарт."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        rig.hang()
        rig.wait_sends(1)
        assert len(rig.sends()) == 1, f"предусловие: зависание не вызвало рестарт; события {rig.events}"

        rig.registry.stop_exitcode = -15
        rig.monitor_runs_during_stop(3)
        rig.execute_restarts()  # PM.restart_process: стоп старого (SIGTERM, -15) идёт при работающем мониторе
        rig.registry.during_stop = None
        rig.beat()  # новое воплощение живо
        for _ in range(4):  # окно, в которое лишний рестарт успел бы запланироваться и отправиться
            time.sleep(_BACKOFF_S * 2)
            rig.tick()

        assert len(rig.sends()) == 1, f"смерть старого воплощения засчитана как новое падение; события {rig.events}"
        assert rig.attempts() == ["1/3"], rig.events
        assert rig.monitor.get_supervision_snapshot()[_NAME]["restart_count"] == 1

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# 5. Ручной process.restart: новое воплощение running, следующее падение лечится ровно один раз
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
@pytest.mark.parametrize("old_exitcode", [0, -15], ids=["old-exits-0", "old-exits-sigterm"])
def test_manual_restart_gives_clean_incarnation_and_next_crash_is_restart_1_of_3(old_exitcode: int) -> None:
    """ACCEPTANCE 5: ручной ``process.restart`` (старое воплощение выходит с 0 / с -15 при работающем мониторе) ->
    новое воплощение ``running`` (на 4 тактах), автоматических рестартов нет; следующее падение -> рестарт 1/3
    ровно один (не пропуск и не двойной)."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()

        rig.registry.stop_exitcode = old_exitcode
        rig.monitor_runs_during_stop(3)
        reply = rig.pm._cmd_process_restart({"process_name": _NAME})  # ручной рестарт, без участия монитора
        rig.registry.during_stop = None
        assert reply["success"] is True, f"предусловие стенда: ручной рестарт не исполнен: {reply}"
        assert rig.pid == 41002, "предусловие стенда: рестарт не создал новое воплощение"

        running = {"previous_states": "running", "supervision_status": "running", "snapshot": "running"}
        for _ in range(4):
            rig.beat()
            rig.tick()
            assert rig.statuses() == running, rig.statuses()
        assert len(rig.sends()) == 0, f"ручной рестарт вызвал авто-рестарт; события {rig.events}"
        assert rig.attempts() == [], rig.events

        rig.crash()
        rig.wait_sends(1)
        assert len(rig.sends()) == 1, f"падение после ручного рестарта пропущено; события {rig.events}"
        rig.execute_restarts()
        rig.beat()
        for _ in range(4):
            time.sleep(_BACKOFF_S * 2)
            rig.tick()

        assert len(rig.sends()) == 1, f"двойной рестарт одной поломки; события {rig.events}"
        assert rig.attempts() == ["1/3"], rig.events

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# 6. Исчерпание попыток: failed достижим, run-state -> fault «сдался» раньше окна 30 с
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_exhausted_restarts_reach_failed_and_run_state_faults_before_grace_window() -> None:
    """ACCEPTANCE 6: ``max_retries`` 2, флаг ``run_auto_restart``, система в ``running``; два падения подряд
    перезапущены (1/2, 2/2, воплощение живёт между падениями), третье падение -> попыток нет: статус ``failed``
    (``supervision.status``), run-state ``fault`` с причиной ``failure`` «cam: супервизор отказался от перезапуска» —
    за время теста, много меньше окна ``run_restart_grace_s`` (30 с, умолчание): причины «не завершён» нет."""

    def scenario() -> None:
        rig = _Rig(run_auto_restart=True, max_retries=2)
        rig.boot()
        pm = rig.pm
        assert pm._run_state == "ready", pm._cmd_system_run_status()
        assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
        assert pm.get_config("run_restart_grace_s", 30.0) == 30.0, "предусловие: окно не короткое"
        started = time.monotonic()

        for k in (1, 2):
            rig.crash()
            rig.wait_sends(k)
            assert len(rig.sends()) == k, f"падение {k} не вызвало рестарт; события {rig.events}"
            rig.execute_restarts()
            rig.beat()
            rig.ticks(2)

        rig.crash()  # третье падение: бюджет (2) исчерпан
        deadline = time.monotonic() + _WAIT_S
        while rig.statuses()["supervision_status"] != "failed" and time.monotonic() < deadline:
            time.sleep(_BACKOFF_S)
            rig.tick()
        rig.ticks(2)  # PM читает снимок монитора ДО его обработки смерти: «сдался» виден со следующего такта

        assert rig.attempts() == ["1/2", "2/2"], rig.events
        assert rig.statuses()["supervision_status"] == "failed", (rig.statuses(), rig.events)
        assert pm._run_state == "fault", pm._cmd_system_run_status()
        status = pm._cmd_system_run_status()
        reasons = status["last_fault"]["reasons"]
        gave_up = [r for r in reasons if r["reason"] == "cam: супервизор отказался от перезапуска"]
        assert len(gave_up) == 1 and gave_up[0]["severity"] == "failure", status
        timeouts = [r for r in reasons if "перезапуск не завершён" in r["reason"]]
        assert timeouts == [], f"fault пришёл по окну, а не по «сдался»: {status}"
        assert time.monotonic() - started < 30.0, "сценарий дольше окна run_restart_grace_s: проверка не показательна"

    _bounded(scenario)
