# -*- coding: utf-8 -*-
"""Task 1.1a (gui-graceful-close) — слепая приёмка: PM отвечает на команды всё окно остановки детей.

Написано ДО реализации по приёмочным критериям брифа; реализация и документы плана не читались.

Обвязка (живые объекты, не двойники): настоящий ``GenericProcessManagerApp`` (message_processor — настоящий
воркер) с настоящим ``SharedResourcesManager``; команды — настоящие сообщения в системную очередь PM, ответы тест
читает из очереди процесса-зонда ``Probe``. «Раннер» воспроизведён так же, как в ``run_process_function``:
поток ждёт ``stop_event`` / ``system_stop_event``, затем ``pm.stop()`` и ``pm.close_root()``.
Ребёнок — фейковый OS-процесс (``is_alive/terminate/kill``), чей выход управляется тестом: «медленный» умирает
через 3,0 с после сигнала ``stop_event``, «упрямый» — только на ``terminate()``. Группа детей — НАСТОЯЩИЕ
``ProcessRegistry.children_stop`` -> ``ChildProcessStop`` (прокси журналирует вызовы и ничего не подменяет).

Наблюдаем: ответы (содержимое, момент прихода), журнал порядка закрытия, счётчики вызовов, отчёт корня.
Ожидаемые значения — литералы. Всё, что может блокироваться, идёт в daemon-потоке с дедлайном join.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import threading
import time
import uuid
from typing import Any

import pytest

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ...app_module.orchestrator import GenericProcessManagerApp
from ..core.stop_budget import stop_budget

SPAWN_DEADLINE_S = 60.0
SLOW_STOP_S = 3.0  # стоп «медленного» ребёнка
REPLY_DEADLINE_S = 12.0  # потолок ожидания ответа: дальше «ответа нет» = упавший ассерт
FAST_REPLY_S = 0.3  # допуск ответа PM внутри окна стопа (по брифу)
MIN_ANSWERS = 5  # успешных supervision.status за окно в 3,0 с


# --------------------------------------------------------------------------- #
# Фейковый ребёнок
# --------------------------------------------------------------------------- #


class _StopEvent:
    """Per-process stop_event ребёнка: ``set()`` сообщает ребёнку о сигнале."""

    def __init__(self, child: "FakeChild") -> None:
        self._child = child
        self._flag = threading.Event()

    def set(self) -> None:
        self._flag.set()
        self._child.on_stop_signal()

    def is_set(self) -> bool:
        return self._flag.is_set()

    def clear(self) -> None:
        self._flag.clear()


class FakeChild:
    """Фейковый OS-процесс. ``mode='slow'``: умирает через ``exit_after_s`` после сигнала;
    ``mode='terminate'``: сигнал игнорирует, умирает на ``terminate()``."""

    def __init__(self, name: str, journal: list[str], *, mode: str, exit_after_s: float = 0.0) -> None:
        self.name = name
        self.pid = 40000 + abs(hash(name)) % 1000
        self.exitcode: int | None = None
        self.mode = mode
        self.exit_after_s = exit_after_s
        self.journal = journal
        self.dead = threading.Event()
        self.stop_signals = 0
        self.terminate_calls = 0
        self.t_stop_signal: float | None = None
        self.t_dead: float | None = None
        self.stop_event = _StopEvent(self)

    def on_stop_signal(self) -> None:
        self.stop_signals += 1
        if self.stop_signals > 1:
            return
        self.t_stop_signal = time.monotonic()
        self.journal.append("child.stop_signal")
        if self.mode == "slow":
            timer = threading.Timer(self.exit_after_s, self._die, args=(0,))
            timer.daemon = True
            timer.start()

    def _die(self, code: int) -> None:
        if self.dead.is_set():
            return
        self.exitcode = code
        self.t_dead = time.monotonic()
        self.journal.append("child.dead")
        self.dead.set()

    def is_alive(self) -> bool:
        return not self.dead.is_set()

    def join(self, timeout: float | None = None) -> None:
        self.dead.wait(timeout)

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.journal.append("child.terminate")
        if self.mode == "terminate":
            self._die(-15)

    def kill(self) -> None:
        self._die(-9)


class _GroupProxy:
    """Журналирует вызовы настоящей группы детей и делегирует ей всё."""

    def __init__(self, real: Any, rig: "Rig") -> None:
        self._real = real
        self._rig = rig

    def __getattr__(self, name: str) -> Any:
        # Task 1.2: прочие публичные методы группы (``signalled_at``) — без журнала, как у настоящей.
        return getattr(self._real, name)

    def request_stop(self) -> None:
        self._rig.journal.append("group.request_stop")
        self._rig.request_stop_calls += 1
        self._real.request_stop()

    def join_until(self, deadline: float) -> bool:
        self._rig.journal.append("children.join_start")
        try:
            return self._real.join_until(deadline)
        finally:
            self._rig.journal.append("children.join_end")

    def kill(self) -> None:
        self._real.kill()

    def close(self) -> None:
        self._real.close()

    def result(self) -> dict:
        return self._real.result()


class _Orchestrator:
    """Оркестратор плагинов: пишет в журнал вести о стопе (поздняя привязка в записи ``plugins-stop``)."""

    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    def request_stop(self) -> None:
        self._journal.append("plugins.request_stop")

    def shutdown(self) -> None:
        self._journal.append("plugins.shutdown")


class Sent:
    def __init__(self, rid: str, command: str, t_send: float) -> None:
        self.rid = rid
        self.command = command
        self.t_send = t_send


class Reply:
    def __init__(self, message: dict, t_arrival: float) -> None:
        self.message = message
        self.t_arrival = t_arrival

    @property
    def result(self) -> Any:
        return self.message.get("result")

    @property
    def success(self) -> Any:
        return self.message.get("success")


class Rig:
    """Живой PM-оркестратор + фейковые дети + зонд ответов + «раннер»."""

    def __init__(self, graceful_s: float) -> None:
        ctx = multiprocessing.get_context("spawn")
        self.system_stop_event = ctx.Event()
        self.srm = SharedResourcesManager()
        assert self.srm.initialize()
        self.srm._system_stop_event = self.system_stop_event
        assert self.srm.register_process("Probe", {"queues": {"system": {"maxsize": 500}}})
        self.journal: list[str] = []
        self.request_stop_calls = 0
        self.children_stop_calls = 0
        self.children: dict[str, FakeChild] = {}
        self.warnings: list[str] = []
        self.pm = GenericProcessManagerApp(
            shared_resources=self.srm,
            config={
                "shutdown_timeout": float(graceful_s),
                "stop_process_timeout": float(graceful_s),
                "initial_state": {"system": {"x": 1}},
            },
        )
        self.pm.attach_stop_budget(stop_budget(graceful_s))
        self._replies: dict[str, Reply] = {}
        self._lock = threading.Lock()
        self._quit = threading.Event()
        self.report: Any = None
        self.runner: threading.Thread | None = None
        self.t_root_closed: float | None = None

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
        assert not th.is_alive(), "PM.initialize() не вернулся за дедлайн"
        assert box.get("ok") is True, f"PM.initialize() не удался: {box}"
        self._instrument()
        threading.Thread(target=self._collect, daemon=True, name="probe-collector").start()
        self.runner = threading.Thread(target=self._runner, daemon=True, name="pm-runner")
        self.runner.start()

    def _instrument(self) -> None:
        pm = self.pm
        registry = pm._process_registry
        original = registry.children_stop

        def children_stop(*, mark_reader_gone: bool) -> _GroupProxy:
            self.children_stop_calls += 1
            return _GroupProxy(original(mark_reader_gone=mark_reader_gone), self)

        registry.children_stop = children_stop
        manager = pm.worker_manager
        real_stop_all = manager.stop_all_workers

        def stop_all_workers(*args: Any, **kwargs: Any) -> Any:
            self.journal.append("workers.stop_all")
            return real_stop_all(*args, **kwargs)

        manager.stop_all_workers = stop_all_workers
        store = pm._state_store_manager
        real_store_shutdown = store.shutdown
        self.store_shutdowns = 0

        def store_shutdown(*args: Any, **kwargs: Any) -> Any:
            self.store_shutdowns += 1
            self.journal.append("state_store")
            return real_store_shutdown(*args, **kwargs)

        store.shutdown = store_shutdown
        real_publish = pm._publish_stop_summary
        self.summaries = 0

        def publish(result: Any) -> Any:
            self.summaries += 1
            self.journal.append("summary")
            return real_publish(result)

        pm._publish_stop_summary = publish
        real_warning = pm._log_warning

        def warn(message: Any, *args: Any, **kwargs: Any) -> Any:
            self.warnings.append(str(message))
            return real_warning(message, *args, **kwargs)

        pm._log_warning = warn
        pm._orchestrator = _Orchestrator(self.journal)

    def add_child(self, name: str, *, mode: str, exit_after_s: float = 0.0) -> FakeChild:
        child = FakeChild(name, self.journal, mode=mode, exit_after_s=exit_after_s)
        registry = self.pm._process_registry
        registry.add_process(child)
        registry._stop_events[name] = child.stop_event
        self.pm._process_configs[name] = {"class": "fake.Child"}
        self.children[name] = child
        return child

    def _runner(self) -> None:
        """Как ``run_process_function``: ждать сигнал, затем ``stop()`` и ``close_root()``."""
        while not self._quit.is_set():
            if self.system_stop_event.is_set() or self.pm.stop_event.is_set():
                break
            time.sleep(0.02)
        else:
            return
        with contextlib.suppress(Exception):
            self.pm.stop()
        with contextlib.suppress(Exception):
            self.report = self.pm.close_root()
        self.t_root_closed = time.monotonic()

    def close(self) -> None:
        self._quit.set()
        with contextlib.suppress(Exception):
            self.system_stop_event.set()
        for child in self.children.values():
            child._die(-9)
        if self.runner is not None:
            self.runner.join(30.0)
        th = threading.Thread(target=self.pm.shutdown, daemon=True, name="pm-shutdown")
        th.start()
        th.join(30.0)

    # ---- запросы и ответы ------------------------------------------------ #

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
        self.srm.queue_registry.get_queue(self.pm.name, "system").put(message)
        return Sent(rid, command, t_send)

    def _collect(self) -> None:
        queue = self.srm.queue_registry.get_queue("Probe", "system")
        while not self._quit.is_set():
            try:
                message = queue.get(timeout=0.02)
            except Exception:  # noqa: BLE001 — пусто / закрытие очереди
                continue
            t_arrival = time.monotonic()
            rid = message.get("request_id") if isinstance(message, dict) else None
            if rid:
                with self._lock:
                    self._replies.setdefault(rid, Reply(message, t_arrival))

    def reply_of(self, sent: Sent) -> Reply | None:
        with self._lock:
            return self._replies.get(sent.rid)

    def wait_reply(self, sent: Sent, timeout: float = REPLY_DEADLINE_S) -> Reply | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            reply = self.reply_of(sent)
            if reply is not None:
                return reply
            time.sleep(0.005)
        return self.reply_of(sent)

    def wait_until(self, predicate: Any, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.005)
        return bool(predicate())

    def wait_root_closed(self, timeout: float) -> bool:
        return self.wait_until(lambda: self.t_root_closed is not None, timeout)


@pytest.fixture
def make_rig():
    rigs: list[Rig] = []

    def factory(graceful_s: float) -> Rig:
        rig = Rig(graceful_s)
        rigs.append(rig)
        rig.start()
        return rig

    try:
        yield factory
    finally:
        for rig in rigs:
            rig.close()


def _bounded(fn: Any, timeout_s: float = 30.0) -> tuple[bool, Any, BaseException | None]:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error")


def _begin_slow_stop(rig: Rig) -> tuple[FakeChild, Sent]:
    """Медленный ребёнок (3,0 с) + ``system.shutdown``; ждёт сигнала ребёнку: окно стопа открыто."""
    child = rig.add_child("slow", mode="slow", exit_after_s=SLOW_STOP_S)
    shutdown = rig.send("system.shutdown")
    assert rig.wait_until(lambda: child.t_stop_signal is not None, 15.0), "ребёнок не получил сигнал стопа"
    assert child.is_alive(), "предусловие: ребёнок уже мёртв — окно стопа не воспроизведено"
    return child, shutdown


# --------------------------------------------------------------------------- #
# Критерий 1
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_supervision_status_answers_while_child_stops_slowly(make_rig) -> None:
    """Пока ребёнок стопается 3,0 с: >= 5 успешных ``supervision.status``, каждый <= 0,3 с;
    ответ на ``system.shutdown`` приходит раньше смерти ребёнка."""
    rig = make_rig(5.0)
    child = rig.add_child("slow", mode="slow", exit_after_s=SLOW_STOP_S)
    shutdown = rig.send("system.shutdown")
    assert rig.wait_until(lambda: child.t_stop_signal is not None, 15.0), "ребёнок не получил сигнал стопа"

    probes: list[Sent] = []
    while child.is_alive() and len(probes) < 40:
        probes.append(rig.send("supervision.status"))
        time.sleep(0.25)
    assert rig.wait_until(lambda: child.t_dead is not None, 15.0), "ребёнок не умер"
    time.sleep(0.5)  # запоздавшие ответы

    shutdown_reply = rig.reply_of(shutdown)
    assert shutdown_reply is not None and shutdown_reply.success is True, "нет успешного ответа на system.shutdown"
    assert shutdown_reply.t_arrival < child.t_dead, "ответ на system.shutdown пришёл после смерти ребёнка"

    good = []
    for sent in probes:
        reply = rig.reply_of(sent)
        if reply is None or reply.success is not True:
            continue
        latency = reply.t_arrival - sent.t_send
        if latency <= FAST_REPLY_S and reply.t_arrival < child.t_dead:
            good.append(round(latency, 3))
    assert len(good) >= MIN_ANSWERS, (
        f"за окно стопа ребёнка (3,0 с) успешных быстрых ответов supervision.status: {len(good)} "
        f"из {len(probes)} запросов, ожидалось >= {MIN_ANSWERS}; latency={good}"
    )


# --------------------------------------------------------------------------- #
# Критерии 2, 4, 7: порядок закрытия
# --------------------------------------------------------------------------- #


def _quick_close(rig: Rig) -> None:
    """Ребёнок выходит за 0,3 с после сигнала; закрытие корня как у раннера."""
    rig.add_child("quick", mode="slow", exit_after_s=0.3)
    rig.pm.stop_event.set()
    assert rig.wait_root_closed(40.0), "корень PM не закрылся за дедлайн"


@pytest.mark.timeout(90)
def test_message_processor_closes_after_children(make_rig) -> None:
    """message_processor (воркеры) закрывается ПОСЛЕ завершения ожидания детей, не до."""
    rig = make_rig(5.0)
    _quick_close(rig)
    journal = list(rig.journal)
    assert "children.join_end" in journal and "workers.stop_all" in journal, journal
    assert journal.index("children.join_end") < journal.index("workers.stop_all"), journal


@pytest.mark.timeout(90)
def test_plugins_stop_requested_before_children_join(make_rig) -> None:
    """Оркестратор плагинов получает ``request_stop`` раньше начала ожидания выхода детей."""
    rig = make_rig(5.0)
    _quick_close(rig)
    journal = list(rig.journal)
    assert "plugins.request_stop" in journal and "children.join_start" in journal, journal
    assert journal.index("plugins.request_stop") < journal.index("children.join_start"), journal


@pytest.mark.timeout(90)
def test_summary_published_after_children_workers_and_state_store(make_rig) -> None:
    """Порядок: дети -> message_processor (workers) -> state_store -> сводка остановки."""
    rig = make_rig(5.0)
    _quick_close(rig)
    steps = [s for s in rig.journal if s in ("children.join_end", "workers.stop_all", "state_store", "summary")]
    first = []
    for step in steps:
        if step not in first:
            first.append(step)
    assert first == ["children.join_end", "workers.stop_all", "state_store", "summary"], rig.journal


# --------------------------------------------------------------------------- #
# Критерий 3: process.restart в окне стопа
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_restart_during_system_stop_is_refused(make_rig) -> None:
    """``process.restart`` в окне стопа детей: ответ ``success=False``, новый процесс не создан, ребёнок не тронут."""
    rig = make_rig(5.0)
    created: list[str] = []
    registry = rig.pm._process_registry
    real_create = registry.create_and_register

    def create_and_register(name: str, *args: Any, **kwargs: Any) -> Any:
        created.append(name)
        return real_create(name, *args, **kwargs)

    registry.create_and_register = create_and_register
    child, _ = _begin_slow_stop(rig)

    restart = rig.send("process.restart", {"process_name": "slow"})
    reply = rig.wait_reply(restart, 8.0)

    assert reply is not None, "process.restart не получил ответа в окне стопа детей"
    assert isinstance(reply.result, dict) and reply.result.get("success") is False, reply.message
    assert reply.t_arrival < (child.t_dead or float("inf")), "ответ на рестарт пришёл после смерти ребёнка"
    assert created == [], f"рестарт создал процесс: {created}"
    assert rig.pm._process_registry.get_process_by_name("slow") is child, "ребёнок заменён"
    assert child.stop_signals == 1, child.stop_signals


# --------------------------------------------------------------------------- #
# Критерий 5: ребёнок, которому нужен terminate
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_slow_child_needing_terminate_leaves_no_survivors(make_rig) -> None:
    """Упрямый ребёнок (умирает на terminate): без выживших, ``shutdown()`` True, state_store и сводка по разу."""
    rig = make_rig(1.0)
    child = rig.add_child("stubborn", mode="terminate")
    rig.pm.stop_event.set()
    assert rig.wait_root_closed(40.0), "корень PM не закрылся за дедлайн"

    assert child.terminate_calls >= 1, "предусловие: terminate не понадобился"
    assert rig.report is not None
    assert rig.report.survivors == (), rig.report
    done, result, error = _bounded(rig.pm.shutdown)
    assert done and error is None, repr(error)
    assert result is True
    assert rig.store_shutdowns == 1, rig.journal
    assert rig.summaries == 1, rig.journal


# --------------------------------------------------------------------------- #
# Критерий 6: повторный system.shutdown в окне стопа
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_repeated_system_shutdown_during_children_stop_is_idempotent(make_rig) -> None:
    """Второй graceful ``system.shutdown``: success, стоп группы запрошен 1 раз; ``force``: mode/deadline_s в ответе."""
    rig = make_rig(5.0)
    child, _ = _begin_slow_stop(rig)

    second = rig.send("system.shutdown")
    second_reply = rig.wait_reply(second, 8.0)
    assert second_reply is not None, "второй system.shutdown не получил ответа в окне стопа"
    assert second_reply.success is True, second_reply.message
    assert rig.request_stop_calls == 1, f"остановка группы запрошена {rig.request_stop_calls} раз(а)"
    assert rig.children_stop_calls == 1, rig.children_stop_calls

    force = rig.send("system.shutdown", {"mode": "force", "deadline_s": 0.5})
    force_reply = rig.wait_reply(force, 8.0)
    assert force_reply is not None, "system.shutdown mode=force не получил ответа в окне стопа"
    assert isinstance(force_reply.result, dict), force_reply.message
    assert force_reply.result.get("mode") == "force", force_reply.result
    assert force_reply.result.get("deadline_s") == 0.5, force_reply.result
    assert rig.pm._force_deadline_s == 0.5, rig.pm._force_deadline_s
    assert rig.request_stop_calls == 1, rig.request_stop_calls


# --------------------------------------------------------------------------- #
# Критерий 8: слой отказа спавна
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_restart_refused_at_spawn_layer_after_system_stop(make_rig) -> None:
    """``restart_process`` НАПРЯМУЮ (мимо шлюза исполнителя) после системного стопа: ``False``, процесс не создан,
    ребёнок не остановлен вторым путём; отказ — строка слоя спавна."""
    rig = make_rig(5.0)
    created: list[str] = []
    registry = rig.pm._process_registry
    real_create = registry.create_and_register

    def create_and_register(name: str, *args: Any, **kwargs: Any) -> Any:
        created.append(name)
        return real_create(name, *args, **kwargs)

    registry.create_and_register = create_and_register
    child, _ = _begin_slow_stop(rig)

    done, result, error = _bounded(lambda: rig.pm.restart_process("slow"), 10.0)

    assert done and error is None, repr(error)
    assert result is False
    assert created == [], f"спавн-слой пропустил создание: {created}"
    assert child.stop_signals == 1, f"прямой restart_process остановил ребёнка повторно: {child.stop_signals}"
    assert any("restart_process(slow)" in line and "отказ" in line for line in rig.warnings), rig.warnings
