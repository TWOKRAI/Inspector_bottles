# -*- coding: utf-8 -*-
"""Task 1.11 (`plans/lifecycle-stop-ownership/tasks/T1.11.md`) — слепая приёмка R1-R9: окно стопа на ребёнка.
Написано ДО реализации; реализация и раздел DESIGN спеки не читались.

Контракт (Goal / REDS T1.11): ключ процесса ``stop_window_s`` задаёт окно стопа ребёнка на всех путях стопа;
ключ PM ``max_stop_window_s`` — потолок окна (по умолчанию ``g`` = graceful PM); внешний срок спавнера считается от
``G = max(g, C)``; негодное значение ключа игнорируется с WARNING.

Обвязка (настоящие объекты, не двойники): настоящий ``ProcessManagerProcess`` в процессе теста с настоящим
``SharedResourcesManager`` и настоящими spawn-детьми. Дети — ``LifecycleChild`` (хук ``stop()`` спит
``stop_delay_s``; не ``IProcessModule`` — раннер бюджет ему не прикладывает) либо его тонкие потомки ``MarkedChild`` /
``SixSecondStopChild`` из этого файла: они дописывают в файл-метку моменты начала и конца ``stop()``.
Команды — настоящие сообщения в системную очередь PM; ответы читаются из очереди процесса-зонда ``Probe``.

Все тесты задают ``stop_process_timeout`` и ``shutdown_timeout`` = 5,0 и потолок явно (conftest ставит 1,0; потолок по
умолчанию ``g`` = 5 обрезал бы любое окно выше 5). Время — ``time.monotonic()`` от отправки команды. Моменты смерти
меряет поток-наблюдатель по ``exitcode`` объекта процесса (без psutil). Всё, что может блокироваться, ждёт с дедлайном.
Ожидаемые значения — литералы из спеки.

Ожидание на дереве до реализации: RED R1, R3, R4, R5 (половина с потолком), R6, R7, R8 (оба пути), R9 (все 10 —
нет WARNING); стражи (зелёные и до, и после) R2, R6b, половина R5 без потолка и с негодным потолком.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import math
import multiprocessing
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ..core.stop_budget import stop_budget
from ..launcher.spawner import ProcessSpawner
from ..process.process_manager_process import ProcessManagerProcess
from ._lifecycle_fifo_helpers import LIFECYCLE_CHILD_CLASS_PATH, LifecycleChild

_THIS_MODULE = "multiprocess_framework.modules.process_manager_module.tests.test_per_child_stop_window_acceptance"
MARKED_CHILD_PATH = f"{_THIS_MODULE}.MarkedChild"
SIX_SECOND_CHILD_PATH = f"{_THIS_MODULE}.SixSecondStopChild"

SPAWN_DEADLINE_S = 90.0  # подъём PM и spawn-детей на загруженной машине
REPLY_DEADLINE_S = 60.0  # потолок ожидания ответа: дальше «ответа нет» = упавший ассерт
DEATH_DEADLINE_S = 40.0  # потолок ожидания смерти ребёнка
CEILING_S = 12.0  # потолок окна по умолчанию в тестах (выше любого окна из REDS)

_QUEUES = {"system": {"maxsize": 100}, "data": {"maxsize": 50}}


# --------------------------------------------------------------------------- #
# Дети
# --------------------------------------------------------------------------- #


class MarkedChild(LifecycleChild):
    """``LifecycleChild`` с журналом стопа: ``stop_begin`` до сна и ``stop_done`` после (в ``stop_marker_path``).

    Сон — ``stop_delay_s`` конфига (дефолт ``DEFAULT_STOP_DELAY_S``). Убитый посреди сна ребёнок ``stop_done`` не пишет.
    """

    DEFAULT_STOP_DELAY_S = 0.0

    def _mark(self, event: str) -> None:
        path = self.config.get("stop_marker_path")
        if path:
            with open(str(path), "a", encoding="utf-8") as fh:
                fh.write(f"{event}\t{time.time():.6f}\n")

    def stop(self) -> None:
        self._mark("stop_begin")
        time.sleep(float(self.config.get("stop_delay_s", self.DEFAULT_STOP_DELAY_S)))
        self._mark("stop_done")


class SixSecondStopChild(MarkedChild):
    """Ребёнок рецепта: конфиг в него не передать, поэтому стоп 6,0 с зашит в класс."""

    DEFAULT_STOP_DELAY_S = 6.0


def child(class_path: str = LIFECYCLE_CHILD_CLASS_PATH, **extra: Any) -> dict[str, Any]:
    """Запись ``processes_config`` для одного ребёнка."""
    return {"class": class_path, "queues": {k: dict(v) for k, v in _QUEUES.items()}, **extra}


def marker_events(path: Path) -> list[str]:
    """События файла-метки ``MarkedChild`` по порядку."""
    if not path.exists():
        return []
    return [line.split("\t")[0] for line in path.read_text(encoding="utf-8").splitlines() if line]


# --------------------------------------------------------------------------- #
# Обвязка
# --------------------------------------------------------------------------- #


class Reply:
    def __init__(self, message: dict, t_arrival: float) -> None:
        self.message = message
        self.t_arrival = t_arrival

    @property
    def result(self) -> Any:
        return self.message.get("result")

    @property
    def outcome(self) -> Any:
        result = self.result
        return result.get("outcome") if isinstance(result, dict) else None


class Sent:
    def __init__(self, rid: str, t_send: float) -> None:
        self.rid = rid
        self.t_send = t_send


class DeathWatch:
    """Поток-наблюдатель: момент (``monotonic``) и ``exitcode`` первого наблюдения смерти каждого процесса.

    Объекты процессов берутся у реестра PM до команды: замена воплощения (restart) наблюдателя не сбивает.
    """

    def __init__(self, procs: dict[str, Any]) -> None:
        self._procs = dict(procs)
        self.deaths: dict[str, tuple[float, int | None]] = {}
        self._quit = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="death-watch")
        self._thread.start()

    def _run(self) -> None:
        while not self._quit.is_set() and len(self.deaths) < len(self._procs):
            for name, proc in self._procs.items():
                if name in self.deaths:
                    continue
                try:
                    code = proc.exitcode
                except ValueError:  # объект процесса закрыт: смерть была, код потерян
                    self.deaths[name] = (time.monotonic(), None)
                    continue
                if code is not None:
                    self.deaths[name] = (time.monotonic(), int(code))
            time.sleep(0.01)

    def wait(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if len(self.deaths) >= len(self._procs):
                return True
            time.sleep(0.01)
        return len(self.deaths) >= len(self._procs)

    def stop(self) -> None:
        self._quit.set()

    def since(self, t0: float, name: str) -> float | None:
        entry = self.deaths.get(name)
        return None if entry is None else entry[0] - t0

    def code(self, name: str) -> int | None:
        entry = self.deaths.get(name)
        return None if entry is None else entry[1]


class _RootHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):
            self._sink.append(record.getMessage())


class StopRig:
    """PM + дети из ``children`` + зонд ответов. Всё ожидание — с дедлайном."""

    def __init__(self, tmp_path: Path, children: dict[str, dict[str, Any]], *, ceiling: Any = CEILING_S) -> None:
        ctx = multiprocessing.get_context("spawn")
        self.system_stop_event = ctx.Event()
        self.srm = SharedResourcesManager()
        assert self.srm.initialize()
        self.srm._system_stop_event = self.system_stop_event
        assert self.srm.register_process("Probe", {"queues": {"system": {"maxsize": 500}}})
        self.tmp_path = tmp_path
        self.children = tuple(children)
        self.pm = ProcessManagerProcess(
            shared_resources=self.srm,
            config={
                "stop_process_timeout": 5.0,
                "shutdown_timeout": 5.0,
                "max_stop_window_s": ceiling,
                "processes_config": dict(children),
            },
        )
        self.pm.attach_stop_budget(stop_budget(5.0))
        self._warnings: list[str] = []
        self._root_handler = _RootHandler(self._warnings)
        self._wrap_pm_warning()
        self._handed: dict[str, dict[str, Any]] = {}
        self._capture_handed_configs()
        self._replies: dict[str, list[Reply]] = {}
        self._lock = threading.Lock()
        self._quit = threading.Event()

    # ---- WARNING --------------------------------------------------------- #

    def _wrap_pm_warning(self) -> None:
        original = self.pm._log_warning

        def _log_warning(message: Any, *args: Any, **kwargs: Any) -> Any:
            self._warnings.append(str(message))
            return original(message, *args, **kwargs)

        self.pm._log_warning = _log_warning

    def _capture_handed_configs(self) -> None:
        """Снять конфиг, переданный созданному ``Process``, в момент создания (до ``start()``: multiprocessing
        удаляет ``_args`` при старте). Ключ ``config`` бандла — 4-й аргумент ``Process``, как в прецеденте
        ``test_stop_budget_child_stop_acceptance.py``."""
        registry = self.pm._process_registry
        original = registry.create_and_register

        def create_and_register(name: str, *args: Any, **kwargs: Any) -> Any:
            proc = original(name, *args, **kwargs)
            if proc is not None:
                with contextlib.suppress(Exception):
                    handed = proc._args[3]["config"]
                    try:
                        self._handed[name] = copy.deepcopy(handed)
                    except Exception:  # noqa: BLE001 — не копируется целиком: хватит и плоской копии
                        self._handed[name] = dict(handed)
            return proc

        registry.create_and_register = create_and_register

    def install_log_capture(self, mp: pytest.MonkeyPatch) -> None:
        """Ещё два канала WARNING: фасад ``StdLoggerFacade`` (blueprint и др.) и корневой stdlib-логгер."""
        sink = self._warnings
        original = StdLoggerFacade.warning

        def warning(facade: Any, msg: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                sink.append(str(msg) % args if args else str(msg))
            except Exception:  # noqa: BLE001 — захват не должен ломать лог
                sink.append(str(msg))
            return original(facade, msg, *args, **kwargs)

        mp.setattr(StdLoggerFacade, "warning", warning)
        logging.getLogger().addHandler(self._root_handler)

    def warnings(self) -> list[str]:
        return list(self._warnings)

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
        # ``initialize()`` менеджер топологии не настраивает (diff_fn/commands_fn ставит прототип): как в тестах
        # ``topology.apply`` фреймворка — fake-планировщик conftest
        # (5 фаз: stop_all -> cleanup -> provision -> create -> start).
        from .conftest import wire_planner

        wire_planner(self.pm)
        for name in self.children:
            proc = self.proc(name)
            assert proc is not None and proc.is_alive(), (
                f"{name} не стартовал — стенд неисправен (или процесс не создан)"
            )
        threading.Thread(target=self._collect, daemon=True, name="probe-collector").start()

    def close(self) -> None:
        """Убрать всё: события, дети (kill — быстро), PM-shutdown в daemon-потоке с дедлайном."""
        self._quit.set()
        with contextlib.suppress(Exception):
            logging.getLogger().removeHandler(self._root_handler)
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

    # ---- процессы и конфиги --------------------------------------------- #

    def proc(self, name: str) -> Any:
        return self.pm._process_registry.get_process_by_name(name)

    def child_config(self, name: str) -> dict[str, Any]:
        """Конфиг, который реестр передал созданному ``Process`` (снят при создании, до ``start()``)."""
        return self._handed[name]

    # ---- запросы и ответы ------------------------------------------------ #

    def _pm_queue(self) -> Any:
        return self.srm.queue_registry.get_queue(self.pm.name, "system")

    def _probe_queue(self) -> Any:
        return self.srm.queue_registry.get_queue("Probe", "system")

    def send(self, command: str, data: dict | None = None) -> Sent:
        rid = uuid.uuid4().hex
        message = {
            "type": "command",
            "command": command,
            "data": dict(data or {}),
            "request_id": rid,
            "sender": "Probe",
        }
        t_send = time.monotonic()
        self._pm_queue().put(message)
        return Sent(rid, t_send)

    def _collect(self) -> None:
        queue = self._probe_queue()
        while not self._quit.is_set():
            try:
                message = queue.get(timeout=0.02)
            except Exception:  # noqa: BLE001 — пусто / закрытие очереди
                continue
            t_arrival = time.monotonic()
            if not isinstance(message, dict) or not message.get("request_id"):
                continue
            with self._lock:
                self._replies.setdefault(message["request_id"], []).append(Reply(message, t_arrival))

    def wait_reply(self, sent: Sent, timeout: float = REPLY_DEADLINE_S) -> Reply | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                got = self._replies.get(sent.rid)
            if got:
                return got[0]
            time.sleep(0.005)
        with self._lock:
            got = self._replies.get(sent.rid)
        return got[0] if got else None

    def timed(self, command: str, data: dict | None = None) -> tuple[float | None, Reply | None]:
        """Отправить команду; вернуть (секунды до ответа от отправки, ответ) или (None, None) по дедлайну."""
        sent = self.send(command, data)
        reply = self.wait_reply(sent)
        return (None if reply is None else reply.t_arrival - sent.t_send), reply


@contextlib.contextmanager
def running_rig(tmp_path: Path, children: dict[str, dict[str, Any]], *, ceiling: Any = CEILING_S) -> Iterator[StopRig]:
    with pytest.MonkeyPatch.context() as mp:
        rig = StopRig(tmp_path, children, ceiling=ceiling)
        rig.install_log_capture(mp)
        try:
            rig.start()
            yield rig
        finally:
            rig.close()


def _within(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def _wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# --------------------------------------------------------------------------- #
# R1-R3: одиночный стоп
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(180)
def test_longer_window_child_exits_itself(tmp_path: Path) -> None:
    """R1: стоп ребёнка 6,0 с, ``stop_window_s: 10.0``, потолок 12: ``process.stop`` -> выход сам,
    ``outcome: "exited"``, ответ 6,0-6,6 с. До: ``terminated`` на 5,0 с."""
    with running_rig(tmp_path, {"slow": child(stop_delay_s=6.0, stop_window_s=10.0)}, ceiling=12.0) as rig:
        elapsed, reply = rig.timed("process.stop", {"process_name": "slow"})

    assert reply is not None, "ответ process.stop не пришёл за дедлайн"
    assert reply.outcome == "exited", f"итог стопа: {reply.result}, ответ через {elapsed:.2f} с"
    assert _within(elapsed, 6.0, 6.6), f"ответ через {elapsed} с, ожидалось 6,0-6,6"


@pytest.mark.timeout(180)
def test_child_without_key_uses_pm_window(tmp_path: Path) -> None:
    """R2 (страж, зелёный до и после): тот же ребёнок без ключа -> ``outcome: "terminated"``, ответ 5,0-5,3 с."""
    with running_rig(tmp_path, {"slow": child(stop_delay_s=6.0)}, ceiling=12.0) as rig:
        elapsed, reply = rig.timed("process.stop", {"process_name": "slow"})

    assert reply is not None, "ответ process.stop не пришёл за дедлайн"
    assert reply.outcome == "terminated", f"итог стопа: {reply.result}, ответ через {elapsed:.2f} с"
    assert _within(elapsed, 5.0, 5.3), f"ответ через {elapsed} с, ожидалось 5,0-5,3"


@pytest.mark.timeout(180)
def test_window_above_ceiling_clamped_with_warning(tmp_path: Path) -> None:
    """R3: ``stop_window_s: 30``, потолок 2,0: WARNING с именем ребёнка, ``30`` и ``2.0``; в конфиге ребёнка
    ``stop_budget.work_s`` 1,2 и ``infra_s`` 0,4 (= ``stop_budget(2.0)``); стоп 6,0 с — ``terminated``,
    ответ 2,0-2,3 с."""
    # ASSUMED: подстрока потолка в WARNING — ``2.0`` (последняя строка REDS R3); в тексте R3 выше сказано ``2``.
    # ASSUMED: WARNING может уйти при создании или при стопе — берутся все WARNING с подъёма PM до конца стопа
    # (``pm._log_warning``, ``StdLoggerFacade.warning``, корневой stdlib-логгер).
    # ASSUMED: потолок читается из ключа ``max_stop_window_s`` конфига PM, окно — из верхнего уровня записи
    # ``processes_config``.
    with running_rig(tmp_path, {"slow": child(stop_delay_s=6.0, stop_window_s=30)}, ceiling=2.0) as rig:
        config = rig.child_config("slow")
        elapsed, reply = rig.timed("process.stop", {"process_name": "slow"})
        warnings = rig.warnings()

    problems: list[str] = []
    budget = config.get("stop_budget") or {}
    if budget.get("work_s") != pytest.approx(1.2):
        problems.append(f"stop_budget.work_s={budget.get('work_s')!r}, ожидалось 1.2")
    if budget.get("infra_s") != pytest.approx(0.4):
        problems.append(f"stop_budget.infra_s={budget.get('infra_s')!r}, ожидалось 0.4")
    if not any("slow" in w and "30" in w and "2.0" in w for w in warnings):
        problems.append(f"нет WARNING с именем 'slow', '30' и '2.0'; WARNING: {warnings}")
    if reply is None:
        problems.append("ответ process.stop не пришёл за дедлайн")
    else:
        if reply.outcome != "terminated":
            problems.append(f"итог стопа {reply.outcome!r}, ожидалось 'terminated'")
        if not _within(elapsed, 2.0, 2.3):
            problems.append(f"ответ через {elapsed} с, ожидалось 2,0-2,3")
    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# R4: системный стоп (корень PM)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
def test_system_stop_respects_per_child_window(tmp_path: Path) -> None:
    """R4: ``system.shutdown`` (путь корня PM), потолок 12: A (``stop_window_s: 12``, стоп 8,0 с) выходит сам,
    ``exitcode`` 0, момент выхода 8,0-9,2 с; B (без ключа, стоп игнорирует) умирает в 5,0-6,2 с."""
    # ASSUMED: корень PM в тесте закрывает сам тест — ``pm.shutdown()`` в daemon-потоке после того, как команда
    # ``system.shutdown`` взвела системное событие (раннера, который зовёт ``shutdown()`` в бою, в стенде нет).
    # ASSUMED: «B игнорирует стоп» = ``stop_delay_s`` 60 с (хук спит дольше любого окна); смерть B — от terminate.
    marks = {"A": tmp_path / "A.stop", "B": tmp_path / "B.stop"}
    children = {
        "A": child(MARKED_CHILD_PATH, stop_delay_s=8.0, stop_window_s=12, stop_marker_path=str(marks["A"])),
        "B": child(MARKED_CHILD_PATH, stop_delay_s=60.0, stop_marker_path=str(marks["B"])),
    }
    with running_rig(tmp_path, children, ceiling=12.0) as rig:
        watch = DeathWatch({"A": rig.proc("A"), "B": rig.proc("B")})
        t0 = time.monotonic()
        rig.send("system.shutdown")
        armed = _wait_until(rig.system_stop_event.is_set, 10.0)
        threading.Thread(target=rig.pm.shutdown, daemon=True, name="root-shutdown").start()
        all_dead = watch.wait(DEATH_DEADLINE_S)
        watch.stop()
        a_events, b_events = marker_events(marks["A"]), marker_events(marks["B"])

    problems: list[str] = []
    if not armed:
        problems.append("system.shutdown не взвёл системное событие за 10 с")
    if not all_dead:
        problems.append(f"не все дети умерли за {DEATH_DEADLINE_S} с: {sorted(watch.deaths)}")
    a_t, b_t = watch.since(t0, "A"), watch.since(t0, "B")
    if not _within(a_t, 8.0, 9.2):
        problems.append(f"A умер через {a_t} с, ожидалось 8,0-9,2")
    if watch.code("A") != 0:
        problems.append(f"A exitcode={watch.code('A')!r}, ожидалось 0 (вышел сам)")
    if "stop_done" not in a_events:
        problems.append(f"A не дошёл до конца stop(): метки {a_events}")
    if not _within(b_t, 5.0, 6.2):
        problems.append(f"B умер через {b_t} с, ожидалось 5,0-6,2")
    if watch.code("B") in (0, None):
        problems.append(f"B exitcode={watch.code('B')!r}, ожидалось ненулевое (убит)")
    if "stop_done" in b_events:
        problems.append(f"B вышел сам: метки {b_events}")
    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# R5: внешний срок спавнера
# --------------------------------------------------------------------------- #


class _FakeOrchestratorProcess:
    """Живой двойник PM для ``ProcessSpawner.stop``: записывает срок внешнего ``join``; после ``join`` мёртв."""

    def __init__(self) -> None:
        self.alive = True
        self.join_timeouts: list[float | None] = []

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        self.alive = False

    def terminate(self) -> None:
        self.alive = False

    def kill(self) -> None:
        self.alive = False


def _outer_join_s(orchestrator_config: dict[str, Any], **stop_kwargs: Any) -> float | None:
    spawner = ProcessSpawner(stop_timeout=5.0, orchestrator_config=orchestrator_config)
    fake = _FakeOrchestratorProcess()
    spawner._process = fake
    spawner.stop(**stop_kwargs)
    return fake.join_timeouts[0] if fake.join_timeouts else None


def test_spawner_outer_budget_from_ceiling() -> None:
    """R5: потолок 10,0, ``shutdown_timeout`` 5,0 -> внешний срок спавнера 13,5 с (10 + 1 + 1 + 1,5); явный
    ``stop(timeout=3.0)`` при том же потолке — тоже 13,5; без потолка ``stop(timeout=3.0)`` — 6,5 (страж ADR-PMM-031);
    негодный потолок ``"abc"`` — ``stop()`` не бросает, 8,5."""
    # ASSUMED: потолок спавнер читает из ``orchestrator_config["max_stop_window_s"]`` (рядом с ``shutdown_timeout``);
    # в спеке сказано лишь «потолок 10,0, shutdown_timeout 5,0».
    with_ceiling = {"shutdown_timeout": 5.0, "max_stop_window_s": 10.0}
    got = {
        "ceiling_10_default_stop": _outer_join_s(with_ceiling),
        "ceiling_10_explicit_3": _outer_join_s(with_ceiling, timeout=3.0),
        "no_ceiling_explicit_3": _outer_join_s({"shutdown_timeout": 5.0}, timeout=3.0),
        "bad_ceiling_abc": _outer_join_s({"shutdown_timeout": 5.0, "max_stop_window_s": "abc"}),
    }
    assert got == pytest.approx(
        {
            "ceiling_10_default_stop": 13.5,
            "ceiling_10_explicit_3": 13.5,
            "no_ceiling_explicit_3": 6.5,
            "bad_ceiling_abc": 8.5,
        }
    )


# --------------------------------------------------------------------------- #
# R6, R6b: бюджет ребёнка из его окна
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(180)
def test_child_stop_budget_from_own_window(tmp_path: Path) -> None:
    """R6: окно 8,0, потолок 12 -> ``work_s`` 5,4, ``infra_s`` 1,0 в конфиге ребёнка (= ``stop_budget(8.0)``)."""
    with running_rig(tmp_path, {"w": child(stop_window_s=8.0)}, ceiling=12.0) as rig:
        budget = rig.child_config("w").get("stop_budget") or {}

    assert budget.get("work_s") == pytest.approx(5.4), f"stop_budget={budget}"
    assert budget.get("infra_s") == pytest.approx(1.0), f"stop_budget={budget}"


@pytest.mark.timeout(180)
def test_keyless_child_budget_not_raised_by_ceiling(tmp_path: Path) -> None:
    """R6b (страж, зелёный до и после): потолок 10, ребёнок без ключа, ``shutdown_timeout`` 5,0 -> ``work_s`` 3,0,
    ``infra_s`` 1,0."""
    with running_rig(tmp_path, {"w": child()}, ceiling=10.0) as rig:
        budget = rig.child_config("w").get("stop_budget") or {}

    assert budget.get("work_s") == pytest.approx(3.0), f"stop_budget={budget}"
    assert budget.get("infra_s") == pytest.approx(1.0), f"stop_budget={budget}"


# --------------------------------------------------------------------------- #
# R7: ключ рецепта доезжает до конфига процесса
# --------------------------------------------------------------------------- #


def _recipe(name: str, class_path: str, window: Any) -> dict[str, Any]:
    """Рецепт с одним процессом; ключ — и на верхнем уровне записи, и в ``extras`` (спека не называет место)."""
    return {
        "processes": [
            {
                "process_name": name,
                "process_class": class_path,
                "stop_window_s": window,
                "extras": {"stop_window_s": window},
            }
        ]
    }


@pytest.mark.timeout(240)
def test_recipe_key_reaches_process_config(tmp_path: Path) -> None:
    """R7: рецепт с ``stop_window_s: 8.0`` у процесса -> ``topology.apply`` -> ``_process_configs[name]["stop_window_s"]
    == 8.0``."""
    # ASSUMED: спека не говорит, где в записи процесса рецепта стоит ключ — он задан и на верхнем уровне записи
    # (``stop_window_s``), и в ``extras``; любое из двух мест, принятое реализацией, даёт зелёный.
    with running_rig(tmp_path, {}, ceiling=12.0) as rig:
        elapsed, reply = rig.timed("topology.apply", {"topology_dict": _recipe("recipe_w", MARKED_CHILD_PATH, 8.0)})
        applied = (rig.pm._process_configs.get("recipe_w") or {}).get("stop_window_s")

    assert reply is not None, "ответ topology.apply не пришёл за дедлайн"
    assert applied == 8.0, f"_process_configs['recipe_w']['stop_window_s']={applied!r}; ответ apply: {reply.result}"


# --------------------------------------------------------------------------- #
# R8: пакетный стоп и рестарт
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
@pytest.mark.parametrize("path", ["topology_apply_batch", "restart_one"])
def test_batch_and_restart_paths_use_child_window(tmp_path: Path, path: str) -> None:
    """R8: потолок 12; меряется момент смерти старых воплощений, не ответ. (а) смена рецепта, снимающая [A, B]
    (``_topology_stop_all``): A (окно 10, стоп 6,0 с) выходит сам в 6,0-7,0 с; B (без ключа, игнорирует стоп) умирает
    в 5,0-6,0 с. (б) ``process.restart A``: старое воплощение A выходит само в 6,0-7,0 с."""
    # ASSUMED: «смена рецепта, снимающая [A, B]» = ``topology.apply`` с ``{"processes": []}`` (A и B пришли из
    # ``processes_config`` PM и в новом рецепте отсутствуют).
    marks = {"A": tmp_path / "A.stop", "B": tmp_path / "B.stop"}
    children = {
        "A": child(MARKED_CHILD_PATH, stop_delay_s=6.0, stop_window_s=10, stop_marker_path=str(marks["A"])),
        "B": child(MARKED_CHILD_PATH, stop_delay_s=60.0, stop_marker_path=str(marks["B"])),
    }
    batch = path == "topology_apply_batch"
    with running_rig(tmp_path, children, ceiling=12.0) as rig:
        watched = {"A": rig.proc("A"), "B": rig.proc("B")} if batch else {"A": rig.proc("A")}
        watch = DeathWatch(watched)
        t0 = time.monotonic()
        sent = (
            rig.send("topology.apply", {"topology_dict": {"processes": []}})
            if batch
            else rig.send("process.restart", {"process_name": "A"})
        )
        all_dead = watch.wait(DEATH_DEADLINE_S)
        reply = rig.wait_reply(sent)
        watch.stop()
        a_events, b_events = marker_events(marks["A"]), marker_events(marks["B"])

    problems: list[str] = []
    if not all_dead:
        problems.append(f"не все старые воплощения умерли за {DEATH_DEADLINE_S} с: {sorted(watch.deaths)}")
    a_t = watch.since(t0, "A")
    if not _within(a_t, 6.0, 7.0):
        problems.append(f"A умер через {a_t} с, ожидалось 6,0-7,0")
    if watch.code("A") != 0:
        problems.append(f"A exitcode={watch.code('A')!r}, ожидалось 0 (вышел сам)")
    if "stop_done" not in a_events:
        problems.append(f"A не дошёл до конца stop(): метки {a_events}")
    if batch:
        b_t = watch.since(t0, "B")
        if not _within(b_t, 5.0, 6.0):
            problems.append(f"B умер через {b_t} с, ожидалось 5,0-6,0")
        if watch.code("B") in (0, None):
            problems.append(f"B exitcode={watch.code('B')!r}, ожидалось ненулевое (убит)")
        if "stop_done" in b_events:
            problems.append(f"B вышел сам: метки {b_events}")
    if reply is None:
        problems.append("ответ команды не пришёл за дедлайн")
    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# R9: негодное значение ключа
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(240)
@pytest.mark.parametrize("entry", ["recipe", "processes_config"])
@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(math.nan, id="nan"),
        pytest.param(True, id="bool_true"),
        pytest.param("8", id="str_8"),
    ],
)
def test_invalid_window_ignored_with_warning(tmp_path: Path, entry: str, bad: Any) -> None:
    """R9: ``stop_window_s`` из {0, -1, NaN, ``True``, ``"8"``} x вход {рецепт через ``topology.apply``,
    ``processes_config`` PM} -> процесс создан, WARNING с именем и ``stop_window_s``, ответ стопа как без ключа (R2):
    ``terminated``, 5,0-5,3 с."""
    # ASSUMED: для входа «рецепт» ребёнок — ``SixSecondStopChild`` (стоп 6,0 с зашит в класс: конфиг в запись
    # рецепта не передать), ключ задан и на верхнем уровне записи, и в ``extras`` (см. R7); для ``processes_config`` —
    # ``LifecycleChild`` со ``stop_delay_s`` 6,0.
    name = "bad_w"
    if entry == "processes_config":
        initial = {name: child(stop_delay_s=6.0, stop_window_s=bad)}
    else:
        initial = {}
    with running_rig(tmp_path, initial, ceiling=12.0) as rig:
        applied_reply = None
        if entry == "recipe":
            _elapsed, applied_reply = rig.timed(
                "topology.apply", {"topology_dict": _recipe(name, SIX_SECOND_CHILD_PATH, bad)}
            )
        proc = rig.proc(name)
        created = proc is not None and proc.is_alive()
        elapsed, reply = rig.timed("process.stop", {"process_name": name}) if created else (None, None)
        warnings = rig.warnings()

    problems: list[str] = []
    if not created:
        problems.append(f"процесс не создан/не жив (ответ apply: {applied_reply and applied_reply.result})")
    if not any(name in w and "stop_window_s" in w for w in warnings):
        problems.append(f"нет WARNING с именем {name!r} и 'stop_window_s'; WARNING: {warnings}")
    if created:
        if reply is None:
            problems.append("ответ process.stop не пришёл за дедлайн")
        else:
            if reply.outcome != "terminated":
                problems.append(f"итог стопа {reply.outcome!r}, ожидалось 'terminated'")
            if not _within(elapsed, 5.0, 5.3):
                problems.append(f"ответ через {elapsed} с, ожидалось 5,0-5,3")
    assert not problems, "; ".join(problems)
