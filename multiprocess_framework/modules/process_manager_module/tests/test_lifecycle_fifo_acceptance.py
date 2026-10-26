# -*- coding: utf-8 -*-
"""Task 1.9b (`plans/lifecycle-stop-ownership.md`) — слепая приёмка R1-R10: команды жизненного цикла PM
вне ``message_processor``. Написано ДО реализации; реализация не читалась.

Контракт (Goal / Acceptance T1.9b): PM не глохнет ни на одну команду, пока ждёт смерти ребёнка; ответ уходит
после подтверждённой смерти через обе двери (прямая команда с request_id и вложенная ``process.command``);
``system.shutdown`` исполняется сразу и снимает очередь; у стопа ребёнка один владелец.

Обвязка (настоящие объекты, не двойники): настоящий ``ProcessManagerProcess`` в процессе теста с настоящим
``SharedResourcesManager``; два настоящих spawn-ребёнка (``LifecycleChild`` из ``_lifecycle_fifo_helpers``):
``slow`` (хук остановки 3,0 с) и ``other`` (быстрый). Конфиг PM: ``stop_process_timeout`` и ``shutdown_timeout`` по 8,0.
Команды — настоящие сообщения в системную очередь PM; ответы тест читает из очереди процесса-зонда ``Probe``.
Корень PM в окне измерений НЕ закрывается (ни раннер, ни ``shutdown()``): ``system.shutdown`` только взводит события.

Наблюдаем только публичное поведение: ответы (содержимое и момент прихода), ``is_alive()``/``exitcode``
ребёнка, строки лога PM, содержимое ``supervision.status``, ``instance_restarts``, журнал принятых ребёнком
внутренних сообщений. Ожидаемые значения — литералы. Всё, что может блокироваться, ждёт с дедлайном.

Ожидание на сегодняшнем коде: RED R1, R2, R4, R5, R6, R7, R10; стражи (зелёные и до, и после) R3, R8, R9.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ..core.stop_budget import stop_budget
from ..process.process_manager_process import ProcessManagerProcess
from ._lifecycle_fifo_helpers import LIFECYCLE_CHILD_CLASS_PATH, PING_COMMAND

STOP_DELAY_S = 3.0  # хук остановки медленного ребёнка
SPAWN_DEADLINE_S = 90.0  # подъём PM + двух spawn-детей на загруженной машине
REPLY_DEADLINE_S = 40.0  # потолок ожидания ответа: дальше «ответа нет» = упавший ассерт
MID_STOP_S = 1.0  # момент измерения: стоп slow идёт (3,0 с), прошла треть
FAST_S = 0.5  # «PM не глохнет»: ответ ≤ 0,5 с
SHUTDOWN_PROBE_S = 0.2  # системный стоп виден ≤ 0,2 с
STOP_LONG_S = 2.5  # стоп действительно был долгим (хук 3,0 с)

PM_LOG_FORBIDDEN = ("did not stop in", "terminating", "всё ещё жив после kill")


# --------------------------------------------------------------------------- #
# Обвязка
# --------------------------------------------------------------------------- #


class Sent:
    """Отправленный запрос: request_id и моменты отправки (monotonic и wall)."""

    def __init__(self, rid: str, command: str, t_send: float, t_wall: float) -> None:
        self.rid = rid
        self.command = command
        self.t_send = t_send
        self.t_wall = t_wall


class Reply:
    """Пришедший ответ: сообщение, момент прихода и «жив ли исходный slow» в этот момент."""

    def __init__(self, message: dict, t_arrival: float, slow_alive: bool) -> None:
        self.message = message
        self.t_arrival = t_arrival
        self.slow_alive = slow_alive

    @property
    def result(self) -> Any:
        return self.message.get("result")

    @property
    def success(self) -> Any:
        return self.message.get("success")


class Rig:
    """PM + два ребёнка + зонд ответов. Всё ожидание — с дедлайном."""

    def __init__(self, tmp_path: Path) -> None:
        ctx = multiprocessing.get_context("spawn")
        self.system_stop_event = ctx.Event()
        self.srm = SharedResourcesManager()
        assert self.srm.initialize()
        self.srm._system_stop_event = self.system_stop_event
        assert self.srm.register_process("Probe", {"queues": {"system": {"maxsize": 500}}})
        self.markers = {"slow": tmp_path / "slow.pings", "other": tmp_path / "other.pings"}
        queues = {"system": {"maxsize": 100}, "data": {"maxsize": 50}}
        processes_config = {
            "slow": {
                "class": LIFECYCLE_CHILD_CLASS_PATH,
                "queues": dict(queues),
                "stop_delay_s": STOP_DELAY_S,
                "marker_path": str(self.markers["slow"]),
            },
            "other": {
                "class": LIFECYCLE_CHILD_CLASS_PATH,
                "queues": dict(queues),
                "stop_delay_s": 0.0,
                "marker_path": str(self.markers["other"]),
            },
        }
        self.pm = ProcessManagerProcess(
            shared_resources=self.srm,
            config={
                "stop_process_timeout": 8.0,
                "shutdown_timeout": 8.0,
                "processes_config": processes_config,
            },
        )
        self.pm.attach_stop_budget(stop_budget(8.0))
        self.log: list[tuple[str, str]] = []
        for level in ("info", "warning", "error"):
            self._record_log(level)
        self.slow0 = None
        self._replies: dict[str, list[Reply]] = {}
        self._lock = threading.Lock()
        self._quit = threading.Event()
        self._collector: threading.Thread | None = None

    def _record_log(self, level: str) -> None:
        original = getattr(self.pm, f"_log_{level}")

        def _log(message: Any, *args: Any, **kwargs: Any) -> Any:
            self.log.append((level, str(message)))
            return original(message, *args, **kwargs)

        setattr(self.pm, f"_log_{level}", _log)

    # ---- подъём / уборка ------------------------------------------------- #

    def start(self) -> None:
        box: dict[str, Any] = {}

        def _init() -> None:
            try:
                box["ok"] = self.pm.initialize()
            except BaseException as exc:  # noqa: BLE001
                box["error"] = repr(exc)

        th = threading.Thread(target=_init, daemon=True, name="pm-initialize")
        th.start()
        th.join(SPAWN_DEADLINE_S)
        assert not th.is_alive(), f"PM.initialize() не вернулся за {SPAWN_DEADLINE_S} с"
        assert box.get("ok") is True, f"PM.initialize() не удался: {box}"
        self.slow0 = self.pm._process_registry.get_process_by_name("slow")
        assert self.slow0 is not None and self.slow0.is_alive(), "slow не стартовал — стенд неисправен"
        other = self.pm._process_registry.get_process_by_name("other")
        assert other is not None and other.is_alive(), "other не стартовал — стенд неисправен"
        self._collector = threading.Thread(target=self._collect, daemon=True, name="probe-collector")
        self._collector.start()

    def close(self) -> None:
        """Убрать всё: события, дети (kill — быстро), PM-shutdown в daemon-потоке с дедлайном."""
        self._quit.set()
        with contextlib.suppress(Exception):
            self.system_stop_event.set()
        with contextlib.suppress(Exception):
            for proc in list(self.pm._process_registry.os_processes):
                if proc.is_alive():
                    proc.kill()
        th = threading.Thread(target=self.pm.shutdown, daemon=True, name="pm-shutdown")
        th.start()
        th.join(40.0)
        with contextlib.suppress(Exception):
            for proc in list(self.pm._process_registry.os_processes):
                if proc.is_alive():
                    proc.kill()
                proc.join(3.0)

    # ---- запросы и ответы ------------------------------------------------ #

    def _pm_queue(self) -> Any:
        return self.srm.queue_registry.get_queue(self.pm.name, "system")

    def _probe_queue(self) -> Any:
        return self.srm.queue_registry.get_queue("Probe", "system")

    def send(self, command: str, data: dict | None = None, *, nested: bool = False) -> Sent:
        """Положить команду в системную очередь PM. ``nested`` — через дверь ``process.command``."""
        rid = uuid.uuid4().hex
        if nested:
            inner = {"cmd": command, **(data or {})}
            message = {
                "type": "command",
                "command": "process.command",
                "data": inner,
                "request_id": rid,
                "sender": "Probe",
            }
        else:
            message = {
                "type": "command",
                "command": command,
                "data": dict(data or {}),
                "request_id": rid,
                "sender": "Probe",
            }
        t_wall = time.time()
        t_send = time.monotonic()
        self._pm_queue().put(message)
        return Sent(rid, command, t_send, t_wall)

    def _collect(self) -> None:
        queue = self._probe_queue()
        while not self._quit.is_set():
            try:
                message = queue.get(timeout=0.02)
            except Exception:  # noqa: BLE001 — пусто / закрытие очереди
                continue
            t_arrival = time.monotonic()
            if not isinstance(message, dict):
                continue
            rid = message.get("request_id")
            if not rid:
                continue
            try:
                alive = bool(self.slow0.is_alive())
            except Exception:  # noqa: BLE001
                alive = False
            with self._lock:
                self._replies.setdefault(rid, []).append(Reply(message, t_arrival, alive))

    def replies(self, sent: Sent) -> list[Reply]:
        with self._lock:
            return list(self._replies.get(sent.rid, []))

    def wait_reply(self, sent: Sent, timeout: float = REPLY_DEADLINE_S) -> Reply | None:
        """Первый ответ на запрос или ``None`` по дедлайну."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = self.replies(sent)
            if got:
                return got[0]
            time.sleep(0.005)
        got = self.replies(sent)
        return got[0] if got else None

    def latency(self, sent: Sent, timeout: float = REPLY_DEADLINE_S) -> tuple[float | None, Reply | None]:
        reply = self.wait_reply(sent, timeout)
        return (None if reply is None else reply.t_arrival - sent.t_send), reply

    def processes(self) -> dict:
        """``supervision.status`` (прямая дверь) -> карта процессов; провал = упавший ассерт."""
        sent = self.send("supervision.status")
        reply = self.wait_reply(sent, 20.0)
        assert reply is not None, "supervision.status не ответил за 20 с"
        assert isinstance(reply.result, dict) and "processes" in reply.result, f"странный ответ: {reply.message}"
        return reply.result["processes"]

    def instance_restarts(self, name: str) -> int:
        return int(self.processes().get(name, {}).get("instance_restarts", 0))

    def wait_until(self, predicate: Callable[[], bool], timeout: float) -> float | None:
        """Секунды до истинности ``predicate`` или ``None`` по дедлайну."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if predicate():
                return time.monotonic() - t0
            time.sleep(0.005)
        return 0.0 if predicate() else None

    # ---- журнал принятых ребёнком внутренних сообщений ------------------- #

    def pings(self, name: str) -> list[tuple[int, float]]:
        path = self.markers[name]
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[2] == PING_COMMAND:
                rows.append((int(parts[0]), float(parts[1])))
        return rows

    @staticmethod
    def ping_message() -> dict:
        return {"type": "command", "command": PING_COMMAND, "data": {}}

    # ---- общие шаги ------------------------------------------------------ #

    def start_slow_stop(self, *, nested: bool = False) -> Sent:
        """``process.stop slow`` и ожидание +1,0 с; предусловие: стоп идёт, ответа ещё нет."""
        sent = self.send("process.stop", {"process_name": "slow"}, nested=nested)
        time.sleep(MID_STOP_S)
        assert self.slow0.is_alive(), "предусловие: slow уже мёртв на +1,0 с — медленный стоп не воспроизведён"
        assert self.replies(sent) == [], "предусловие: ответ на process.stop пришёл до смерти ребёнка"
        return sent


@pytest.fixture
def rig(tmp_path: Path):
    r = Rig(tmp_path)
    try:
        r.start()
        yield r
    finally:
        r.close()


def _log_lines(rig: Rig) -> list[str]:
    return [message for _level, message in list(rig.log)]


# --------------------------------------------------------------------------- #
# R1-R2, R4-R5, R10: PM не глохнет, пока ждёт смерти ребёнка
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(150)
def test_supervision_status_answers_during_long_child_stop(rig: Rig) -> None:
    """R1: на +1,0 с стопа slow прямой ``supervision.status`` отвечает ≤ 0,5 с (до: ≥ 2,0 с)."""
    stop = rig.start_slow_stop()

    status = rig.send("supervision.status")
    lat, reply = rig.latency(status)

    assert reply is not None, "supervision.status не ответил за дедлайн, пока шёл стоп slow"
    assert reply.success is True, f"supervision.status ответил не успехом: {reply.message}"
    assert lat <= FAST_S, (
        f"supervision.status ответил за {lat:.2f} с во время стопа slow, ожидалось ≤ {FAST_S} (до: ≥ 2,0)"
    )
    # Стоп не сорван: ответ на него приходит потом и с успехом.
    stop_reply = rig.wait_reply(stop)
    assert stop_reply is not None and stop_reply.success is True, (
        f"стоп slow не завершился успехом: {stop_reply and stop_reply.message}"
    )


@pytest.mark.timeout(150)
def test_relay_to_other_process_during_long_stop_delivered_fast(rig: Rig) -> None:
    """R2: на +1,0 с стопа slow ``process.relay`` в other: other получил сообщение ≤ 0,5 с, ответ relay ≤ 0,5 с."""
    rig.start_slow_stop()

    relay = rig.send("process.relay", {"target_process": "other", "inner_message": rig.ping_message()})
    lat, reply = rig.latency(relay)

    assert reply is not None, "ответ process.relay не пришёл за дедлайн, пока шёл стоп slow"
    assert lat <= FAST_S, f"ответ process.relay за {lat:.2f} с во время стопа slow, ожидалось ≤ {FAST_S} (до: ≥ 2,0)"
    assert reply.result == {"success": True, "target_process": "other"}, f"содержимое ответа relay: {reply.result}"

    assert rig.wait_until(lambda: len(rig.pings("other")) >= 1, 15.0) is not None, (
        "other не получил внутреннее сообщение"
    )
    rows = rig.pings("other")
    assert len(rows) == 1, f"other получил {len(rows)} сообщений вместо 1: {rows}"
    delivered_after = rows[0][1] - relay.t_wall
    assert delivered_after <= FAST_S, (
        f"other получил сообщение через {delivered_after:.2f} с, ожидалось ≤ {FAST_S} (до: ≥ 2,0)"
    )


@pytest.mark.timeout(150)
def test_stop_via_process_command_door_deferred_same_content(rig: Rig) -> None:
    """R4: ``process.command {cmd: process.stop}`` — ``process.command.response`` с тем же содержимым и success;
    пока он ждёт, ``supervision.status`` отвечает ≤ 0,5 с (до: ≥ 2,0 с)."""
    stop = rig.start_slow_stop(nested=True)

    status = rig.send("supervision.status")
    lat, status_reply = rig.latency(status)
    assert status_reply is not None, "supervision.status не ответил, пока process.command ждёт смерти slow"
    assert lat <= FAST_S, (
        f"supervision.status за {lat:.2f} с, пока process.command ждёт стоп slow, ожидалось ≤ {FAST_S} (до: ≥ 2,0)"
    )

    reply = rig.wait_reply(stop)
    assert reply is not None, "process.command.response на стоп не пришёл за дедлайн"
    assert reply.message.get("command") == "process.command.response", f"ответ не той двери: {reply.message}"
    assert reply.success is True, f"process.command.response: success={reply.success}"
    assert reply.result == {"success": True, "process_name": "slow"}, f"содержимое ответа: {reply.result}"
    assert reply.slow_alive is False, "process.command.response пришёл, пока slow ещё жив"
    assert reply.t_arrival - stop.t_send >= STOP_LONG_S, "ответ пришёл раньше, чем мог закончиться стоп в 3,0 с"


@pytest.mark.timeout(150)
def test_system_shutdown_during_stop_sets_events_immediately(rig: Rig) -> None:
    """R5: на +1,0 с стопа slow ``system.shutdown``: ``system_stop_event`` взведён ≤ 0,2 с после отправки
    (до: на +3,0...3,6 с). Корень PM не закрывается."""
    rig.start_slow_stop()
    assert not rig.system_stop_event.is_set(), "предусловие: system_stop_event взведён до system.shutdown"

    rig.send("system.shutdown")
    waited = rig.wait_until(rig.system_stop_event.is_set, 15.0)

    assert waited is not None, "system_stop_event не взведён за 15 с после system.shutdown"
    delay = waited
    assert delay <= SHUTDOWN_PROBE_S, (
        f"system_stop_event взведён через {delay:.2f} с после отправки system.shutdown, ожидалось ≤ {SHUTDOWN_PROBE_S} "
        "(до: на +3,0...3,6 с)"
    )


@pytest.mark.timeout(150)
def test_supervision_status_alive_through_topology_apply_with_slow_stop(rig: Rig) -> None:
    """R10: ``topology.apply``, убирающий slow (стоп 3,0 с): ``supervision.status`` во время него ≤ 0,5 с."""
    # Планировщик убирает только slow: остановка (долгая) и снятие ресурсов.
    rig.pm._topology_manager.configure(
        diff_fn=lambda current, desired: {"has_changes": True},
        commands_fn=lambda diff, desired: [
            {"cmd": "process.stop_all", "process_names": ["slow"]},
            {"cmd": "process.cleanup", "process_name": "slow"},
        ],
    )
    apply_sent = rig.send("topology.apply", {"topology_dict": {"processes": {}}})
    time.sleep(MID_STOP_S)
    assert rig.slow0.is_alive(), "предусловие: slow уже мёртв на +1,0 с — стоп в topology.apply не воспроизведён"
    assert rig.replies(apply_sent) == [], "предусловие: topology.apply уже ответил (стоп slow не шёл)"

    status = rig.send("supervision.status")
    lat, reply = rig.latency(status)

    assert reply is not None, "supervision.status не ответил за дедлайн во время topology.apply"
    assert lat <= FAST_S, (
        f"supervision.status за {lat:.2f} с во время topology.apply со стопом slow, ожидалось ≤ {FAST_S} (до: ≥ 2,0)"
    )
    applied = rig.wait_reply(apply_sent)
    assert applied is not None and applied.success is True, (
        f"topology.apply не завершился успехом: {applied and applied.message}"
    )


# --------------------------------------------------------------------------- #
# R3: страж содержимого; R6-R7: системный стоп; R8-R9: стражи
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(150)
def test_stop_reply_after_confirmed_death_direct_door(rig: Rig) -> None:
    """R3 (страж): ответ ``process.stop`` — не раньше, чем ``is_alive()`` ребёнка стал False; содержимое
    ``{"success": True, "process_name": "slow"}``."""
    stop = rig.send("process.stop", {"process_name": "slow"})
    reply = rig.wait_reply(stop)

    assert reply is not None, "ответ process.stop не пришёл за дедлайн"
    assert reply.slow_alive is False, (
        "ответ process.stop пришёл, пока slow ещё жив (is_alive() == True в момент прихода)"
    )
    assert reply.result == {"success": True, "process_name": "slow"}, f"содержимое ответа: {reply.result}"
    assert reply.success is True
    assert reply.t_arrival - stop.t_send >= STOP_LONG_S, "ответ пришёл раньше, чем мог закончиться стоп в 3,0 с"
    assert rig.slow0.exitcode == 0, f"exitcode slow = {rig.slow0.exitcode}, ожидалось 0"


@pytest.mark.timeout(150)
def test_queued_lifecycle_ops_rejected_on_system_stop(rig: Rig) -> None:
    """R6: стоп slow + в очереди ``process.restart other``; затем ``system.shutdown``: ответ рестарта
    ``{"success": False, "error": "system_stopping"}`` ≤ 0,5 с, ``instance_restarts`` other не вырос."""
    before = rig.instance_restarts("other")
    stop = rig.send("process.stop", {"process_name": "slow"})
    time.sleep(MID_STOP_S)
    assert rig.replies(stop) == [], "предусловие: стоп slow уже завершён"
    restart = rig.send("process.restart", {"process_name": "other"})
    shutdown = rig.send("system.shutdown")

    reply = rig.wait_reply(restart)
    assert reply is not None, "ответ process.restart не пришёл за дедлайн"
    lat = reply.t_arrival - shutdown.t_send
    assert isinstance(reply.result, dict), f"ответ рестарта не словарь: {reply.message}"
    assert reply.result.get("success") is False and reply.result.get("error") == "system_stopping", (
        f"ответ рестарта в очереди при системном стопе: {reply.result}, ожидалось success=False, error=system_stopping "
        "(до: рестарт исполняется после стопа)"
    )
    assert lat <= FAST_S, f"ответ рестарта пришёл через {lat:.2f} с после system.shutdown, ожидалось ≤ {FAST_S}"
    # Хвост: дождаться ответа на стоп (текущая операция), затем счётчик.
    assert rig.wait_reply(stop) is not None, "ответ на process.stop не пришёл за дедлайн"
    after = rig.instance_restarts("other")
    assert after == before, f"instance_restarts other: было {before}, стало {after}; рестарт не должен исполниться"


@pytest.mark.timeout(150)
def test_system_stop_mid_single_stop_one_owner(rig: Rig) -> None:
    """R7: системный стоп посреди одиночного стопа slow: slow выходит с exitcode 0, в логе PM 0 строк
    ``did not stop in`` / ``terminating`` / ``всё ещё жив после kill``, сводка стопа ``reported=true``; ответ
    ``process.stop slow`` ≤ 0,5 с после отправки ``system.shutdown``, ``success: False``."""
    stop = rig.start_slow_stop()
    shutdown = rig.send("system.shutdown")

    reply = rig.wait_reply(stop)
    assert reply is not None, "ответ process.stop не пришёл за дедлайн после system.shutdown"
    lat = reply.t_arrival - shutdown.t_send
    assert lat <= FAST_S, f"ответ process.stop за {lat:.2f} с после system.shutdown, ожидалось ≤ {FAST_S} (до: на +3 с)"
    assert reply.success is False and isinstance(reply.result, dict) and reply.result.get("success") is False, (
        f"прерванный стоп должен ответить success=False, получено: {reply.message} (до: success=True)"
    )

    rig.slow0.join(20.0)
    assert not rig.slow0.is_alive(), "slow не вышел за 20 с"
    assert rig.slow0.exitcode == 0, f"exitcode slow = {rig.slow0.exitcode}, ожидалось 0 (прерванный стоп без terminate)"
    time.sleep(1.0)  # дать PM дописать лог после смерти ребёнка
    lines = _log_lines(rig)
    for needle in PM_LOG_FORBIDDEN:
        hits = [line for line in lines if needle in line]
        assert not hits, f"в логе PM есть строки «{needle}»: {hits}"
    report = rig.pm._process_registry.exit_report("slow")
    assert report.get("reported") is True, f"сводка стопа slow: {report}, ожидалось reported=True"


@pytest.mark.timeout(150)
def test_relay_to_target_in_restart_reaches_new_incarnation(rig: Rig) -> None:
    """R8 (страж): ``process.relay`` в slow на +1,0 с после ``process.restart slow`` (идёт стоп 3,0 с):
    новое воплощение получает сообщение, 1 из 1."""
    restart = rig.send("process.restart", {"process_name": "slow"})
    time.sleep(MID_STOP_S)
    assert rig.slow0.is_alive(), "предусловие: slow уже мёртв на +1,0 с — стоп в рестарте не воспроизведён"
    old_pid = rig.slow0.pid
    relay = rig.send("process.relay", {"target_process": "slow", "inner_message": rig.ping_message()})

    restarted = rig.wait_reply(restart)
    assert restarted is not None and restarted.success is True, (
        f"process.restart slow: {restarted and restarted.message}"
    )
    relayed = rig.wait_reply(relay)
    assert relayed is not None, "ответ process.relay не пришёл за дедлайн"
    assert relayed.result == {"success": True, "target_process": "slow"}, f"содержимое ответа relay: {relayed.result}"

    new_pid = rig.processes()["slow"]["pid"]
    assert new_pid != old_pid, "slow не получил нового воплощения"
    assert rig.wait_until(lambda: len(rig.pings("slow")) >= 1, 15.0) is not None, (
        "ни одно воплощение slow не получило сообщение; хвост лога PM: "
        + " | ".join(f"{lvl}:{msg[:160]}" for lvl, msg in rig.log[-12:] if lvl != "info")
    )
    time.sleep(1.0)  # окно для дубля / запоздавшей доставки
    rows = rig.pings("slow")
    assert [pid for pid, _t in rows] == [new_pid], (
        f"получатели (pid): {[p for p, _ in rows]}, ожидался один — новое воплощение {new_pid} (старое {old_pid})"
    )


@pytest.mark.timeout(150)
def test_lifecycle_commands_keep_arrival_order(rig: Rig) -> None:
    """R9 (страж порядка): ``process.stop slow``, сразу за ним ``process.restart other``: ответ restart после
    ответа stop, ``instance_restarts`` other = +1."""
    before = rig.instance_restarts("other")
    stop = rig.send("process.stop", {"process_name": "slow"})
    restart = rig.send("process.restart", {"process_name": "other"})

    stop_reply = rig.wait_reply(stop)
    restart_reply = rig.wait_reply(restart)
    assert stop_reply is not None, "ответ process.stop не пришёл за дедлайн"
    assert restart_reply is not None, "ответ process.restart не пришёл за дедлайн"
    assert stop_reply.result == {"success": True, "process_name": "slow"}, f"ответ stop: {stop_reply.result}"
    assert restart_reply.result == {"success": True, "process_name": "other"}, f"ответ restart: {restart_reply.result}"
    assert stop_reply.t_arrival < restart_reply.t_arrival, (
        f"ответ restart ({restart_reply.t_arrival - restart.t_send:.2f} с) раньше ответа stop "
        f"({stop_reply.t_arrival - stop.t_send:.2f} с): порядок прибытия нарушен"
    )
    after = rig.instance_restarts("other")
    assert after == before + 1, f"instance_restarts other: было {before}, стало {after}, ожидалось +1"
