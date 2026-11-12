# -*- coding: utf-8 -*-
"""Task 1.4 (system-run-state) — слепые приёмочные тесты последовательности STOP (REDS 1-10).

Написано ДО реализации по наблюдаемым требованиям брифа (DESIGN/FILES и ``plans/**`` не читались).

Контракт (из брифа): ``system.run.stop`` из ``running`` отвечает сразу
``{"success": True, "accepted": True, "state": "stopping"}``; последовательность идёт вне потока обработки
сообщений: шаги ``pre_stop`` (тот же список, что у graceful-close) -> ``run_event.clear()`` -> ожидание ``paused: true``
у всех ожидаемых процессов, не дольше ``run_stop_timeout_s``. Итог: все подтвердили -> ``ready``/``not_ready`` по
оценке готовности; срок истёк -> ``not_ready`` + причина ``failure`` «<процесс> не подтвердил остановку за <N> с».
Мёртвый процесс считается остановленным. Авария (``fault``) шаги ``pre_stop`` пропускает, остаётся в ``fault``,
помечается ``fault_stop_done``. START во время ``stopping`` отказан. ``system.shutdown`` из ``running`` — один проход
``pre_stop`` и событие ``shutdown`` в машину до взвода событий останова системы.

Обвязка (настоящие объекты): ``ProcessManagerProcess`` (``make_pm`` + настоящий ``_create_components`` под патчем
реестра, как в ``test_run_commands``) + настоящий ``ProcessMonitor``. Входы — то, что PM видит в бою: heartbeat с
полем ``readiness`` (``monitor._on_heartbeat_received``) и такт ``monitor._run_iteration()``. Дети — «двойник
детей» ``_ChildSim``: поток, раз в 10 мс шлёт heartbeat; ``paused`` обедающего (``obey``) ребёнка равно «run_event
снят» — как у настоящего ребёнка, который встаёт на паузу по снятому событию. Время управляемое: ``run_stop_timeout_s``
в десятых долях секунды. Всё, что может блокироваться, — в daemon-потоке с join-дедлайном или цикле ожидания с
дедлайном; ожидаемые значения — литералы.

Допущения тестера (полный список — в отчёте):
  * список шагов ``pre_stop`` задаётся так же, как у graceful-close: ``pm._pre_stop_steps`` + ``pm._pre_stop_executor``
    (двойник исполнителя ``submit(action, key, reply)`` на daemon-потоке) + ``pm.router_manager.request_async``;
  * ожидаемые процессы = ключи ``pm._process_configs``; ожидание ``paused`` читает листы ``readiness`` монитора само
    (такты монитора в тестах ручные, ожидание на них не висит);
  * признак «остановка в аварии завершена» — атрибут PM, имя которого содержит ``fault_stop_done`` (ищется по имени);
  * число ``<N>`` в тексте причины — ``0.5`` (одинаково пишется и ``str(0.5)``, и ``{:g}``).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

from ..core.stop_budget import stop_budget
from ..monitor.process_monitor import ProcessMonitor
from ..process.pre_stop import PreStopStep
from ..process.process_manager_process import ProcessManagerProcess
from .conftest import make_pm
from .test_run_commands import _PM_MOD, _reason, tick

_DEADLINE_S = 10.0  # потолок любого ожидания: дальше «не дождались» = упавший ассерт
_TIMEOUT_S = 0.5  # run_stop_timeout_s в тестах со сроком (в тексте причины -> "0.5")
_STOP_REPLY = {"success": True, "accepted": True, "state": "stopping"}


def _wait(predicate: Callable[[], bool], timeout: float) -> bool:
    """Ждать условие до дедлайна; итог — выполнилось ли."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _bounded(fn: Callable[[], Any], deadline_s: float) -> Any:
    """Вызвать ``fn`` в daemon-потоке с join-дедлайном: вызов, который виснет, — упавший ассерт, не зависший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="run-stop-bounded")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _fault_stop_done(pm: ProcessManagerProcess) -> Any:
    """Значение признака «остановка в аварии завершена»; ``None`` — такого атрибута у PM нет совсем."""
    for name in sorted(set(vars(pm)) | set(dir(type(pm)))):
        if "fault_stop_done" in name:
            return getattr(pm, name)
    return None


def _unconfirmed(reasons: list[dict], node: str) -> list[dict]:
    """Причины «не подтвердил остановку» по узлу ``node``."""
    return [r for r in reasons if r.get("node") == node and "не подтвердил остановку" in str(r.get("reason"))]


def _unconfirmed_expected(node: str) -> dict:
    return {
        "node": node,
        "severity": "failure",
        "reason": f"{node} не подтвердил остановку за {_TIMEOUT_S} с",
        "source": "report",
    }


# --------------------------------------------------------------------------- #
# Двойники и обвязка
# --------------------------------------------------------------------------- #


class _LoggedEvent:
    """Обёртка над настоящим событием работы: ``set()``/``clear()`` пишутся в общий журнал порядка."""

    def __init__(self, inner: Any, log: list[str]) -> None:
        self._inner = inner
        self._log = log

    def set(self) -> None:
        self._log.append("set")
        self._inner.set()

    def clear(self) -> None:
        self._log.append("clear")
        self._inner.clear()

    def is_set(self) -> bool:
        return self._inner.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._inner.wait(timeout)


class _StopEventSpy:
    """Двойник ``_system_stop_event``: на ``set()`` пишет в журнал и запоминает состояние машины работы в этот миг."""

    def __init__(self, rig: "_Rig") -> None:
        self._rig = rig
        self._flag = threading.Event()

    def set(self) -> None:
        self._rig.log.append("stop_events")
        self._rig.state_at_stop_events.append(str(getattr(self._rig.pm._run_state, "value", self._rig.pm._run_state)))
        self._flag.set()

    def is_set(self) -> bool:
        return self._flag.is_set()

    def clear(self) -> None:
        self._flag.clear()

    def wait(self, timeout: float | None = None) -> bool:
        return self._flag.wait(timeout)


class _ThreadExecutor:
    """Двойник исполнителя ``pm-pre-stop``: ``submit(action, key, reply)`` -> действие на daemon-потоке и ``reply``."""

    def submit(self, action: Callable, key: Any, reply: Callable) -> bool:
        def run() -> None:
            result: Any = None
            try:
                result = action()
            finally:
                reply(result)

        threading.Thread(target=run, daemon=True, name="run-stop-pre-stop-exec").start()
        return True


class _StepRouter:
    """Фейк ``router_manager``: ``request_async`` пишет шаг в журнал и отвечает успехом с ДРУГОГО потока.

    ``gate`` — шаг держится, пока тест не взведёт его (окно «идёт pre_stop»); по умолчанию взведён.
    """

    def __init__(self, rig: "_Rig", hold: bool) -> None:
        self.rig = rig
        self.requests: list[str] = []
        self.event_set_at_request: list[bool] = []
        self.gate = threading.Event()
        if not hold:
            self.gate.set()

    def request_async(self, message: dict, on_response: Callable, timeout: float = 5.0) -> str:
        command = str(message["command"])
        self.requests.append(command)
        self.event_set_at_request.append(self.rig.pm._run_event.is_set())
        self.rig.log.append(f"step:{command}")

        def answer() -> None:
            self.gate.wait(_DEADLINE_S)
            on_response({"type": "response", "success": True, "result": {}})

        threading.Thread(target=answer, daemon=True, name="run-stop-step-answer").start()
        return "cid"


def _beat(
    monitor: ProcessMonitor,
    name: str,
    *,
    ready: bool,
    reasons: list[dict],
    paused: bool,
    age_s: float,
) -> None:
    """Heartbeat ребёнка с листом ``readiness`` (``at`` = сейчас - ``age_s``)."""
    now = time.time()
    monitor._on_heartbeat_received(
        {
            "sender": name,
            "timestamp": now,
            "readiness": {"ready": ready, "reasons": list(reasons), "paused": paused, "at": now - age_s},
        }
    )


class _ChildSim:
    """Двойник детей: поток шлёт heartbeat каждые 10 мс по «режиму» процесса.

    Режимы: ``obey`` — ``paused`` = «run_event снят» (и ``gate`` взведён, если задан); ``stuck`` — живой, свежий отчёт,
    но ``paused`` всегда false; ``stale`` — отчёт устарел на час (живой процесс без свежего отчёта), ``paused`` false;
    ``silent`` — не шлёт ничего.
    """

    def __init__(self, pm: ProcessManagerProcess, monitor: ProcessMonitor, names: tuple[str, ...]) -> None:
        self._pm = pm
        self._monitor = monitor
        self.cfg: dict[str, dict[str, Any]] = {
            n: {"mode": "obey", "ready": True, "reasons": [], "gate": None} for n in names
        }
        self._quit = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="run-stop-child-sim")
        self._thread.start()

    def set(self, name: str, **fields: Any) -> None:
        self.cfg[name] = {**self.cfg[name], **fields}

    def beat_now(self) -> None:
        """Один круг heartbeat-ов синхронно (определённое состояние листов в точке теста)."""
        event_set = self._pm._run_event.is_set()
        for name, cfg in list(self.cfg.items()):
            mode = cfg["mode"]
            if mode == "silent":
                continue
            age = 3600.0 if mode == "stale" else 0.0
            if mode == "obey":
                gate = cfg.get("gate")
                paused = (not event_set) and (gate is None or gate.is_set())
            else:
                paused = False
            _beat(self._monitor, name, ready=cfg["ready"], reasons=cfg["reasons"], paused=paused, age_s=age)

    def _run(self) -> None:
        while not self._quit.is_set():
            self.beat_now()
            self._quit.wait(0.01)

    def close(self) -> None:
        self._quit.set()
        self._thread.join(_DEADLINE_S)


class _Rig:
    """PM + монитор + двойник детей. Шаги ``pre_stop`` — по флагу ``steps``; ``hold_step`` держит ответ шага."""

    def __init__(
        self,
        names: tuple[str, ...] = ("cam",),
        *,
        timeout_s: float = _TIMEOUT_S,
        steps: bool = False,
        hold_step: bool = False,
    ) -> None:
        configs = {n: {"class": f"pkg.{n}"} for n in names}
        pm = make_pm(process_configs=configs)
        registry = pm._process_registry  # MockProcessRegistry с живыми MockProcess по ключам configs
        pm.update_config("run_gate", True)
        pm.update_config("heartbeat_interval", 5.0)
        pm.update_config("heartbeat_interval_sec", 5.0)
        pm.update_config("run_stop_timeout_s", timeout_s)  # ДО _create_components: годится и при чтении на старте
        with (
            patch(f"{_PM_MOD}.ProcessRegistry"),
            patch(f"{_PM_MOD}.ProcessPriority"),
            patch(f"{_PM_MOD}.ProcessStatusMonitor"),
            patch(f"{_PM_MOD}.ProcessMonitor"),
            patch(f"{_PM_MOD}.QueueRegistry"),
        ):
            pm._create_components()
        pm._process_registry = registry
        monitor = ProcessMonitor(pm, poll_interval=0.01, heartbeat_timeout=15.0)
        pm._process_monitor = monitor
        pm.communication = MagicMock()
        pm.communication.broadcast.return_value = 1  # число получателей: монитор сравнивает его с нулём
        pm.attach_stop_budget(stop_budget(5.0))
        self.log: list[str] = []
        self.state_at_stop_events: list[str] = []
        pm._run_event = _LoggedEvent(pm._run_event, self.log)
        pm._system_stop_event = _StopEventSpy(self)
        self.router = _StepRouter(self, hold_step)
        pm.router_manager = self.router
        if steps:
            pm._pre_stop_steps = (PreStopStep(process=names[0], command="robot.home", timeout_s=3.0),)
            pm._pre_stop_executor = _ThreadExecutor()
        pm._run_apply("settled", ready=True)  # итог boot-барьера
        self.pm = pm
        self.monitor = monitor
        self.sim = _ChildSim(pm, monitor, names)

    def close(self) -> None:
        self.sim.close()
        self.router.gate.set()  # отпустить зависшие ответы шагов

    # --- входы теста ---------------------------------------------------------------------------------

    def tick(self) -> None:
        tick(self.pm, self.monitor)

    def to_running(self) -> None:
        """Здоровые процессы отчитались -> такт -> START -> ``running``; журнал порядка очищается."""
        self.sim.beat_now()
        self.tick()
        assert self.pm._run_state == "ready"
        assert self.pm._cmd_system_run_start() == {"success": True, "state": "running"}
        assert self.pm._run_event.is_set() is True
        self.log.clear()

    def stop(self) -> dict:
        """``system.run.stop`` в daemon-потоке с дедлайном: команда не должна блокировать вызывающего."""
        return _bounded(self.pm._cmd_system_run_stop, _DEADLINE_S)

    # --- наблюдения ----------------------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self.pm._run_snapshot()[0].value

    def wait_not_stopping(self, timeout: float = _DEADLINE_S) -> bool:
        return _wait(lambda: self.state != "stopping", timeout)

    def status(self) -> dict:
        return self.pm._cmd_system_run_status()


@pytest.fixture
def rig_factory():
    rigs: list[_Rig] = []

    def make(*args: Any, **kwargs: Any) -> _Rig:
        rig = _Rig(*args, **kwargs)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        rig.close()


# --------------------------------------------------------------------------- #
# 1. Порядок: pre_stop -> снятие события
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_runs_pre_stop_then_clears_event(rig_factory) -> None:
    """STOP из ``running`` с одним шагом: ответ сразу ``stopping`` (шаг ещё идёт, поток приёма свободен); пока шаг
    идёт, ``run_event`` ВЗВЕДЕНО; шаг ровно один; снятие события — только после шага; итог ``ready``."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True, hold_step=True)
    rig.to_running()

    assert rig.stop() == _STOP_REPLY

    assert _wait(lambda: "step:robot.home" in rig.log, 3.0), f"шаг pre_stop не начался: {rig.log}"
    assert rig.state == "stopping"
    assert rig.pm._run_event.is_set() is True, "событие снято до конца шагов pre_stop"
    assert "clear" not in rig.log, rig.log
    assert rig.router.event_set_at_request == [True]

    rig.router.gate.set()  # шаг отвечает
    assert rig.wait_not_stopping(), f"STOP не завершился: {rig.log}"
    assert rig.log[0] == "step:robot.home", rig.log
    assert rig.log[1] == "clear", rig.log
    assert rig.log.count("step:robot.home") == 1, rig.log
    assert rig.pm._run_event.is_set() is False
    assert rig.state == "ready"


# --------------------------------------------------------------------------- #
# 2. Ожидание paused у всех
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_waits_all_paused_then_ready(rig_factory) -> None:
    """Два процесса: ``cam`` встаёт на паузу сразу, ``plc`` — только когда тест его отпустит. Пока ``plc`` не
    подтвердил, состояние ``stopping`` (срок 10 с не истёк); после подтверждения — ``ready``, причин нет."""
    rig = rig_factory(("cam", "plc"), timeout_s=10.0)
    gate = threading.Event()
    rig.sim.set("plc", gate=gate)
    rig.to_running()

    assert rig.stop() == _STOP_REPLY

    assert _wait(lambda: rig.pm._run_event.is_set() is False, 3.0), "событие не снято"
    hold_until = time.monotonic() + 0.3
    while time.monotonic() < hold_until:
        assert rig.state == "stopping", f"STOP завершился, пока plc не подтвердил paused: {rig.state}"
        time.sleep(0.01)

    gate.set()  # plc подтверждает паузу
    assert rig.wait_not_stopping(5.0), "STOP не завершился после подтверждения paused всеми"
    status = rig.status()
    assert status["state"] == "ready", status
    assert status["reasons"] == [], status
    assert status["last_fault"] is None, status


# --------------------------------------------------------------------------- #
# 3. Срок истёк
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_timeout_not_ready_with_named_process(rig_factory) -> None:
    """``plc`` живой и свежо отчитывается, но ``paused`` не подтверждает: по сроку 0.5 с — ``not_ready`` и ровно одна
    причина ``failure`` «plc не подтвердил остановку за 0.5 с» (source ``report``); ``cam`` в причинах нет."""
    rig = rig_factory(("cam", "plc"), timeout_s=_TIMEOUT_S)
    rig.sim.set("plc", mode="stuck")
    rig.to_running()

    t0 = time.monotonic()
    assert rig.stop() == _STOP_REPLY

    assert rig.wait_not_stopping(6.0), "STOP не завершился по сроку"
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.4, f"STOP закончился за {elapsed:.2f} с — раньше срока 0.5 с"
    status = rig.status()
    assert status["state"] == "not_ready", status
    assert status["start_allowed"] is False, status
    assert _unconfirmed(status["reasons"], "plc") == [_unconfirmed_expected("plc")], status["reasons"]
    assert _unconfirmed(status["reasons"], "cam") == [], status["reasons"]


# --------------------------------------------------------------------------- #
# 4-5. Авария: pre_stop пропущен, fault остаётся
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_fault_skips_pre_stop(rig_factory) -> None:
    """Якорь: из ``running`` STOP шаг ВЫПОЛНЯЕТ (один запрос). Авария (потеря готовности в ``running``) при тех же
    шагах — не выполняет ни одного, при том что последовательность остановки в аварии доходит до конца."""
    anchor = rig_factory(("cam",), steps=True)
    anchor.to_running()
    assert anchor.stop() == _STOP_REPLY
    assert anchor.wait_not_stopping(), "якорь: STOP не завершился"
    assert anchor.router.requests == ["robot.home"], "якорь: STOP из running обязан исполнить шаг pre_stop"

    rig = rig_factory(("cam",), steps=True)
    rig.to_running()
    rig.sim.set("cam", ready=False, reasons=[_reason("failure", "cam")])
    rig.sim.beat_now()

    rig.tick()  # running + failure -> fault

    assert rig.state == "fault"
    assert _wait(lambda: _fault_stop_done(rig.pm) is True, 5.0), "остановка в аварии не завершилась (fault_stop_done)"
    assert rig.router.requests == [], f"авария исполнила шаги pre_stop: {rig.router.requests}"
    assert rig.state == "fault"


@pytest.mark.timeout(60)
def test_fault_stop_done_keeps_fault(rig_factory) -> None:
    """После подтверждения paused всеми авария ОСТАЁТСЯ ``fault`` (не ``stopping``/``ready``), ``fault_stop_done`` true,
    ``last_fault`` не квитирован; START по-прежнему отказан ``fault_unacknowledged``."""
    rig = rig_factory(("cam", "plc"), timeout_s=5.0)
    rig.to_running()
    store_writes: list[tuple[str, Any]] = []

    class _Store:
        def handle_state_set(self, msg: dict) -> dict:
            data = msg["data"]
            store_writes.append((data["path"], data["value"]))
            return {"status": "ok", "path": data["path"], "changed": True}

    rig.pm._state_store_manager = _Store()
    rig.sim.set("cam", ready=False, reasons=[_reason("failure", "cam")])
    rig.sim.beat_now()

    rig.tick()

    assert _wait(lambda: _fault_stop_done(rig.pm) is True, 5.0), "fault_stop_done не взведён"
    time.sleep(0.1)  # остаётся fault и потом
    status = rig.status()
    assert status["state"] == "fault", status
    assert status["last_fault"] is not None and status["last_fault"]["acknowledged_at"] is None, status
    states = [v for p, v in store_writes if p == "system.run.state"]
    assert "stopping" not in states, f"авария заходила в stopping: {states}"
    assert states[-1] == "fault", states
    start = rig.pm._cmd_system_run_start()
    assert start["success"] is False and start["error"] == "fault_unacknowledged", start


# --------------------------------------------------------------------------- #
# 6. Мёртвый процесс = остановлен
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_dead_process_counts_as_stopped_not_timeout(rig_factory) -> None:
    """``plc`` умер при ``running``. Срок 8 с, ждём ≤ 4 с: ожидание на мёртвом не висит. Итог ``not_ready`` с
    причиной «процесс не жив» (liveness); причины «не подтвердил остановку» нет."""
    rig = rig_factory(("cam", "plc"), timeout_s=8.0)
    rig.to_running()
    rig.pm._process_registry._processes["plc"]._alive = False
    rig.sim.set("plc", mode="silent")

    assert rig.stop() == _STOP_REPLY

    assert rig.wait_not_stopping(4.0), "STOP висит на мёртвом процессе (ждёт срок 8 с)"
    status = rig.status()
    assert status["state"] == "not_ready", status
    dead = [r for r in status["reasons"] if r.get("node") == "plc"]
    assert [(r["severity"], r["reason"], r["source"]) for r in dead] == [("failure", "процесс не жив", "liveness")], (
        dead
    )
    assert [r for r in status["reasons"] if "не подтвердил остановку" in str(r.get("reason"))] == []


# --------------------------------------------------------------------------- #
# 7. Живой, но без свежего отчёта: ждёт до срока; в аварии причина — в last_fault
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_alive_stale_process_waits_paused_until_timeout_then_reason_in_last_fault(rig_factory) -> None:
    """``plc`` жив, но отчёт устарел (авария по «нет отчёта о готовности»). Подтверждения paused нет -> ждём срок
    0.5 с (не меньше), затем причина «plc не подтвердил остановку за 0.5 с» в ``last_fault.reasons``; состояние
    ``fault``; START отказан ``fault_unacknowledged`` с этой причиной."""
    rig = rig_factory(("cam", "plc"), timeout_s=_TIMEOUT_S)
    rig.to_running()
    rig.sim.set("plc", mode="stale")
    rig.sim.beat_now()

    t0 = time.monotonic()
    rig.tick()  # running + нет свежего отчёта plc -> fault

    assert rig.state == "fault"

    def reason_in_last_fault() -> bool:
        last_fault = rig.status()["last_fault"]
        return last_fault is not None and bool(_unconfirmed(last_fault["reasons"], "plc"))

    assert _wait(reason_in_last_fault, 6.0), f"причина не попала в last_fault: {rig.status()['last_fault']}"
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.4, f"причина появилась через {elapsed:.2f} с — раньше срока 0.5 с"
    status = rig.status()
    assert status["state"] == "fault", status
    assert _unconfirmed(status["last_fault"]["reasons"], "plc") == [_unconfirmed_expected("plc")], status["last_fault"]
    start = rig.pm._cmd_system_run_start()
    assert start["success"] is False and start["error"] == "fault_unacknowledged", start
    assert _unconfirmed(start["reasons"], "plc") == [_unconfirmed_expected("plc")], start


# --------------------------------------------------------------------------- #
# 8. Множество «не подтвердивших остановку»
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_unconfirmed_stop_reason_survives_tick_clears_on_paused(rig_factory) -> None:
    """После STOP по сроку ``plc`` в множестве «не подтвердил остановку»: оценка добавляет причину, такт её не стирает
    (ровно одна, не по одной на такт), START отказан ``not_ready``. Как только лист ``plc`` показал ``paused: true``,
    такт убирает причину и система снова ``ready``."""
    rig = rig_factory(("cam", "plc"), timeout_s=_TIMEOUT_S)
    rig.sim.set("plc", mode="stuck")
    rig.to_running()
    assert rig.stop() == _STOP_REPLY
    assert rig.wait_not_stopping(6.0), "STOP не завершился по сроку"
    assert rig.state == "not_ready"

    rig.tick()
    rig.tick()
    status = rig.status()
    assert status["state"] == "not_ready", status
    assert _unconfirmed(status["reasons"], "plc") == [_unconfirmed_expected("plc")], "такт стёр или удвоил причину"
    start = rig.pm._cmd_system_run_start()
    assert start["success"] is False and start["error"] == "not_ready", start
    assert _unconfirmed(start["reasons"], "plc") == [_unconfirmed_expected("plc")], start

    rig.sim.set("plc", mode="obey")  # plc встал на паузу (событие уже снято)
    rig.sim.beat_now()
    rig.tick()
    status = rig.status()
    assert status["reasons"] == [], status
    assert status["state"] == "ready", status
    assert status["start_allowed"] is True, status


# --------------------------------------------------------------------------- #
# 9. START во время stopping
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_start_during_stopping_refused(rig_factory) -> None:
    """Шаг ``pre_stop`` держится -> состояние ``stopping``: START отказан ``stopping``; после завершения STOP
    состояние ``ready`` (START не прошёл: ни ``running``, ни взведённого события)."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True, hold_step=True)
    rig.to_running()
    assert rig.stop() == _STOP_REPLY
    assert _wait(lambda: "step:robot.home" in rig.log, 3.0), f"шаг pre_stop не начался: {rig.log}"
    assert rig.state == "stopping"

    reply = rig.pm._cmd_system_run_start()

    assert reply["success"] is False, reply
    assert reply["error"] == "stopping", reply
    assert reply["state"] == "stopping", reply
    rig.router.gate.set()
    assert rig.wait_not_stopping(), "STOP не завершился"
    assert rig.state == "ready"
    assert rig.pm._run_event.is_set() is False, "отказанный START взвёл событие"


# --------------------------------------------------------------------------- #
# 10. system.shutdown из running
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("mode", ["graceful", "force"])
def test_shutdown_from_running_single_pre_stop_pass(rig_factory, mode: str) -> None:
    """``system.shutdown`` из ``running``: событие ``shutdown`` подано в машину ДО взвода событий останова системы
    (в миг ``set()`` состояние уже ``shutting_down``). ``graceful`` дополнительно: шаг ``pre_stop`` выполнен РОВНО
    ОДИН раз, порядок — шаг, снятие ``run_event``, события останова системы."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True)
    rig.to_running()

    reply = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": mode}), _DEADLINE_S)

    assert reply.get("accepted") is True or mode == "force", reply
    assert _wait(lambda: rig.pm._system_stop_event.is_set(), _DEADLINE_S), f"события останова не взведены: {rig.log}"
    # события останова взводятся идемпотентно, возможно дважды (поток шагов и ответ исполнителя): везде одно состояние
    assert rig.state_at_stop_events, "события останова не взводились"
    assert set(rig.state_at_stop_events) == {"shutting_down"}, rig.state_at_stop_events
    if mode == "graceful":
        assert rig.log.count("step:robot.home") == 1, f"проходов pre_stop не один: {rig.log}"
        assert rig.router.requests == ["robot.home"], rig.router.requests
        assert rig.log.index("step:robot.home") < rig.log.index("clear") < rig.log.index("stop_events"), rig.log
