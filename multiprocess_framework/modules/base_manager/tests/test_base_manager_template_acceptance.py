"""Слепая приёмка Task 1.2b-1: шаблонный ``BaseManager.shutdown()`` и ``scope``.

Контракт (``plans/2026-10-03_lifecycle-owner-scope/tasks/1.2b.md``): ``shutdown()`` —
шаблон: первый вызов закрывает привязанную область, затем один раз зовёт
``_on_shutdown()``; результат кэшируется; реентрантный вызов и вызов из потока
поддерева области — ``False`` сразу; ``scope`` — только чтение, ``attach_scope``
повторно запрещён, pickle области не видит; корень процесса даёт областям
пять менеджеров по путям DESIGN 4.

Тесты написаны ДО реализации, по брифу, а не по коду. Ожидаемые значения —
литералы из спека. Всё, что может зависнуть, идёт в daemon-потоке со сроком.
Тестовый подкласс определяет ``_on_shutdown``, а не ``shutdown``.
"""

from __future__ import annotations

import logging
import pickle
import threading
import time
import uuid

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.modules.process_module import ProcessModule

# DESIGN 4 (литералы спека, `ProcessModule("p", config={})`).
ROOT_SCOPE_PATHS = {
    "stats_manager": "proc/p/planes/stats_manager-scope",
    "observation_manager": "proc/p/planes/observation_manager-scope",
    "router_manager": "proc/p/transport/router_manager-scope",
    "command_manager": "proc/p/transport/command_manager-scope",
    "console_manager": "proc/p/transport/console_manager-scope",
}
DEADLINE_S = 10.0

# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def call_bounded(fn, timeout_s: float):
    """Вызвать ``fn`` в daemon-потоке; вернуть (завершился, результат, ошибка, длительность)."""
    box: dict = {}

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=run, daemon=True, name="call_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error"), box.get("elapsed")


class Journal:
    """Журнал наблюдаемых событий: порядок записей."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self._lock = threading.Lock()

    def add(self, event: str) -> None:
        with self._lock:
            self.events.append(event)

    def count(self, event: str) -> int:
        with self._lock:
            return self.events.count(event)


class TemplateManager(BaseManager):
    """Тестовый подкласс: определяет ``_on_shutdown`` (не ``shutdown``)."""

    def __init__(self, name: str, hook=None) -> None:
        super().__init__(name)
        self._hook = hook

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def _on_shutdown(self) -> bool:
        if self._hook is None:
            return True
        return self._hook(self)


class PlainManager(BaseManager):
    """Без хука и без потоков в состоянии: годится для pickle."""

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def _on_shutdown(self) -> bool:
        return True


@pytest.fixture
def make_scope():
    """Настоящие области через ``open_scope``; все корни закрываются в teardown (G3: корни ``t02…``)."""
    roots: list = []

    def factory():
        root = open_scope(f"t02{uuid.uuid4().hex[:10]}", budget_s=2.0)
        roots.append(root)
        return root

    yield factory
    for root in roots:
        try:
            root.close()
        except Exception:  # noqa: BLE001 - уборка, не предмет теста
            pass


def make_process() -> ProcessModule:
    proc = ProcessModule("p", config={})
    assert proc.initialize() is True
    return proc


# ---------------------------------------------------------------------------
# 1. G-1
# ---------------------------------------------------------------------------


def test_on_shutdown_called_once() -> None:
    journal = Journal()

    def hook(_mgr) -> bool:
        journal.add("on_shutdown")
        return True

    mgr = TemplateManager("once_mgr", hook)
    results = []
    for _ in range(3):
        done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
        assert done, "shutdown() завис"
        assert error is None, repr(error)
        results.append(result)
    assert journal.count("on_shutdown") == 1
    assert results == [True, True, True]


# ---------------------------------------------------------------------------
# 2. G-2b: настоящая область закрыта раньше _on_shutdown
# ---------------------------------------------------------------------------


def test_scope_closed_before_on_shutdown(make_scope) -> None:
    journal = Journal()
    scope = make_scope()
    scope.own(lambda: journal.add("scope_resource_released"), name="res")

    def hook(mgr) -> bool:
        journal.add("on_shutdown")
        journal.add(f"scope.closed={mgr.scope.closed}")
        return True

    mgr = TemplateManager("order_mgr", hook)
    mgr.attach_scope(scope)
    assert mgr.scope is scope

    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done, "shutdown() завис"
    assert error is None, repr(error)
    assert result is True
    assert journal.events == ["scope_resource_released", "on_shutdown", "scope.closed=True"]


# ---------------------------------------------------------------------------
# 3. G-3: исключение -> False, строка лога, область закрыта
# ---------------------------------------------------------------------------


def test_exception_gives_false_and_closes_scope(make_scope, caplog) -> None:
    journal = Journal()
    scope = make_scope()
    scope.own(lambda: journal.add("scope_resource_released"), name="res")

    def hook(_mgr) -> bool:
        raise RuntimeError("kaboom")

    mgr = TemplateManager("boom_mgr", hook)
    mgr.attach_scope(scope)
    caplog.set_level(logging.DEBUG)

    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done, "shutdown() завис"
    assert error is None, f"исключение вышло из shutdown(): {error!r}"
    assert result is False
    assert scope.closed is True
    assert journal.events == ["scope_resource_released"]
    expected = "shutdown boom_mgr: _on_shutdown упал: RuntimeError: kaboom"
    messages = [record.getMessage() for record in caplog.records]
    assert any(expected in message for message in messages), messages


# ---------------------------------------------------------------------------
# 4. G-10: второй вызов из другого потока ждёт и получает результат первого
# ---------------------------------------------------------------------------


def test_second_call_other_thread_gets_first_result() -> None:
    entered = threading.Event()
    gate = threading.Event()
    journal = Journal()

    def hook(_mgr) -> bool:
        journal.add("on_shutdown")
        entered.set()
        gate.wait(DEADLINE_S)
        return False

    mgr = TemplateManager("race_mgr", hook)
    box: dict = {}

    def first() -> None:
        box["first"] = mgr.shutdown()

    def second() -> None:
        box["second"] = mgr.shutdown()
        box["second_at"] = time.monotonic()

    a = threading.Thread(target=first, daemon=True, name="first_call")
    b = threading.Thread(target=second, daemon=True, name="second_call")
    try:
        a.start()
        assert entered.wait(DEADLINE_S), "первый вызов не дошёл до _on_shutdown"
        b.start()
        time.sleep(0.3)
        assert b.is_alive(), "второй вызов не должен возвращаться, пока первый не закончил"
        released_at = time.monotonic()
        gate.set()
        a.join(DEADLINE_S)
        b.join(DEADLINE_S)
        assert not a.is_alive() and not b.is_alive(), "shutdown() завис"
    finally:
        gate.set()
    assert box["first"] is False
    assert box["second"] is False
    assert box["second_at"] >= released_at
    assert journal.count("on_shutdown") == 1


# ---------------------------------------------------------------------------
# 5. G-11: реентрантный вызов -> False сразу
# ---------------------------------------------------------------------------


def test_reentrant_call_returns_false_at_once() -> None:
    inner: dict = {}
    journal = Journal()

    def hook(mgr) -> bool:
        journal.add("on_shutdown")
        t0 = time.monotonic()
        inner["result"] = mgr.shutdown()
        inner["elapsed"] = time.monotonic() - t0
        return True

    mgr = TemplateManager("reentrant_mgr", hook)
    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done, "реентрантный shutdown() завис"
    assert error is None, repr(error)
    assert inner["result"] is False
    assert inner["elapsed"] < 1.0, f"реентрантный вызов ждал {inner['elapsed']:.3f} с"
    assert result is True
    assert journal.count("on_shutdown") == 1


# ---------------------------------------------------------------------------
# 6. G-5: pickle с привязанной областью
# ---------------------------------------------------------------------------


def test_pickle_with_scope(make_scope) -> None:
    scope = make_scope()
    mgr = PlainManager("pickled_mgr")
    mgr.attach_scope(scope)

    blob = pickle.dumps(mgr)
    restored = pickle.loads(blob)

    assert restored.manager_name == "pickled_mgr"
    assert restored.scope is None
    assert mgr.scope is scope, "pickle не должен трогать область исходного менеджера"


# ---------------------------------------------------------------------------
# 7. G-12: повторный attach_scope
# ---------------------------------------------------------------------------


def test_attach_twice_refused(make_scope) -> None:
    first = make_scope()
    other = make_scope()
    mgr = PlainManager("attach_mgr")
    mgr.attach_scope(first)

    with pytest.raises(RuntimeError):
        mgr.attach_scope(other)
    with pytest.raises(RuntimeError):
        mgr.attach_scope(first)
    assert mgr.scope is first


# ---------------------------------------------------------------------------
# 8. G-13 / DESIGN 4: области менеджеров корня (настоящий ProcessModule)
# ---------------------------------------------------------------------------


def test_root_attributes_get_scopes() -> None:
    proc = make_process()
    try:
        for attr, path in ROOT_SCOPE_PATHS.items():
            manager = getattr(proc, attr)
            assert manager.scope is not None, f"{attr}: области нет"
            assert manager.scope.path == path
            assert manager.scope.closed is False

        with_scope = {
            name for name, value in vars(proc).items() if isinstance(value, BaseManager) and value.scope is not None
        }
        assert with_scope == {
            "stats_manager",
            "observation_manager",
            "router_manager",
            "command_manager",
            "console_manager",
            "executor_manager",  # Task 1.9m: область "executor_manager-scope" в work корня
        }

        # config={}: этих менеджеров нет, области им не достаются.
        assert proc.error_manager is None
        assert proc.shared_resources is None
        # не BaseManager / не через _attr_call: области нет.
        assert getattr(proc._orchestrator, "scope", None) is None
        assert proc.logger_manager.scope is None
        assert proc.worker_manager.scope is None
    finally:
        call_bounded(proc.shutdown, 20.0)


# ---------------------------------------------------------------------------
# 9. G-6: поток области менеджера остановлен корнем раньше shutdown() менеджера
# ---------------------------------------------------------------------------


def test_manager_thread_stopped_by_process_root() -> None:
    journal = Journal()
    started = threading.Event()
    proc = make_process()
    try:
        manager = proc.stats_manager
        real_shutdown = manager.shutdown

        def spy_shutdown(*args, **kwargs):
            journal.add("manager.shutdown")
            return real_shutdown(*args, **kwargs)

        manager.shutdown = spy_shutdown

        def target(stop_event: threading.Event) -> None:
            journal.add("t.started")
            started.set()
            stop_event.wait(DEADLINE_S)
            journal.add("t.exit")

        manager.scope.spawn(target, name="t")
        assert started.wait(DEADLINE_S), "поток области не стартовал"

        done, _, error, _ = call_bounded(proc.shutdown, 20.0)
        assert done, "proc.shutdown() завис"
        assert error is None, repr(error)
        assert journal.events == ["t.started", "t.exit", "manager.shutdown"]
    finally:
        call_bounded(proc.shutdown, 20.0)


# 10. G-11b: поток области зовёт shutdown() -> False; _on_shutdown идёт на главном потоке
#
# Подмена менеджера после initialize(): до 1.2b-2 у пяти менеджеров корня остаются свои
# `shutdown` (мягкий режим, ChannelRoutingManager и др.), шаблон у них не работает. Поэтому
# `stats_manager` заменяется тестовым подклассом с настоящей областью из сегмента корня;
# корень гасит его позднесвязанным `_attr_call(…, "shutdown")` на потоке `proc.shutdown()`.
# ---------------------------------------------------------------------------


def test_scope_thread_shutdown_false_on_shutdown_on_main() -> None:
    started = threading.Event()
    seen: dict = {}
    proc = make_process()
    original = proc.stats_manager
    try:

        def hook(mgr) -> bool:
            seen["on_shutdown_thread"] = threading.get_ident()
            seen["scope_closed_then"] = mgr.scope.closed
            return True

        swapped = TemplateManager("swapped_stats", hook)
        swapped.attach_scope(proc.lifetime_segments["planes"].child("swapped-scope"))
        proc.stats_manager = swapped

        def target(stop_event: threading.Event) -> None:
            seen["scope_thread"] = threading.get_ident()
            started.set()
            stop_event.wait(DEADLINE_S)
            seen["result_in_scope_thread"] = swapped.shutdown()

        swapped.scope.spawn(target, name="t")
        assert started.wait(DEADLINE_S), "поток области не стартовал"

        def run_root_shutdown() -> bool:
            seen["main_thread"] = threading.get_ident()
            return proc.shutdown()

        done, _, error, _ = call_bounded(run_root_shutdown, 20.0)
        assert done, "proc.shutdown() завис"
        assert error is None, repr(error)

        assert seen["result_in_scope_thread"] is False
        assert seen["on_shutdown_thread"] == seen["main_thread"]
        assert seen["on_shutdown_thread"] != seen["scope_thread"]
        assert seen["scope_closed_then"] is True
    finally:
        call_bounded(proc.shutdown, 20.0)
        call_bounded(original.shutdown, 20.0)
