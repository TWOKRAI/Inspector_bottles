# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 1.9m: ``ExecutorManager`` (REDS R1-R5).

Написаны независимым тестером ТОЛЬКО по контракту ``plans/lifecycle-stop-ownership/tasks/T1.9m.md``
(D2, D5, D7) и разделу «REDS — слепой тестер» ``T1.9m_facts.md``; реализации ``ExecutorManager``
в дереве тестера нет. Ожидаемые значения - литералы из R-формулировок.

Ожидание до реализации: R1-R5 красные по отсутствию модуля ``worker_module.executor_manager``
(``ImportError`` внутри теста). Новые имена импортируются ВНУТРИ тестов, а не на уровне модуля:
каждый тест докладывает свой красный, а не один ошибкой сбора на весь файл.

Стенд: настоящий ``WorkerManager(manager_name="t", process=None)`` + ``initialize()`` (имя потока
рабочего - ``"t_keyed-<имя>-<i>"``), настоящая область ``base_manager.open_scope``. WARNING/ERROR
менеджера ловит фейк-логгер в слоте ``managers={"logger": fake}`` (без слота миксин молчит).
Каждый ждущий вызов - в daemon-потоке с дедлайном ``join``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.worker_module import WorkerManager

# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


def run_bounded(fn: Callable[[], Any], timeout: float = 10.0) -> Any:
    """Выполнить ``fn`` в daemon-потоке с дедлайном ``join``; не уложилась - провал, а не зависание."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["ret"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробросим в потоке теста
            box["exc"] = exc

    t = threading.Thread(target=target, name="probe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pytest.fail(f"вызов не вернулся за {timeout} с (зависание)")
    if "exc" in box:
        raise box["exc"]
    return box.get("ret")


class FakeLogger:
    """Слот ``logger`` менеджера: запоминает записи по уровням (образец - command_module fork-тест)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, message: Any) -> None:
        with self._lock:
            self.records.append((level, str(message() if callable(message) else message)))

    def debug(self, message: Any, **kw: Any) -> None:
        self._add("debug", message)

    def info(self, message: Any, **kw: Any) -> None:
        self._add("info", message)

    def warning(self, message: Any, **kw: Any) -> None:
        self._add("warning", message)

    def error(self, message: Any, **kw: Any) -> None:
        self._add("error", message)

    def critical(self, message: Any, **kw: Any) -> None:
        self._add("critical", message)

    def at(self, level: str) -> list[str]:
        with self._lock:
            return [m for lvl, m in self.records if lvl == level]


class Env:
    """Один ``WorkerManager`` процесса "t" + фабрики менеджера и областей, с уборкой."""

    def __init__(self) -> None:
        self.wm = WorkerManager(manager_name="t", process=None)
        assert self.wm.initialize() is True
        self.log = FakeLogger()
        self._scopes: list[Any] = []
        self._managers: list[Any] = []

    def manager(self, *, scope_budget_s: float | None = None) -> Any:
        from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager

        mgr = ExecutorManager("t_executors", worker_manager=self.wm, managers={"logger": self.log})
        self._managers.append(mgr)
        assert mgr.initialize() is True
        if scope_budget_s is not None:
            scope = open_scope("t/exec", budget_s=scope_budget_s)
            self._scopes.append(scope)
            mgr.attach_scope(scope)
        return mgr

    @property
    def scope(self) -> Any:
        return self._scopes[-1]

    def close(self) -> None:
        for mgr in self._managers:
            try:
                run_bounded(mgr.shutdown, 10.0)
            except BaseException:  # noqa: BLE001 - уборка не маскирует провал теста
                pass
        for scope in self._scopes:
            try:
                run_bounded(scope.close, 10.0)
            except BaseException:  # noqa: BLE001
                pass
        try:
            run_bounded(self.wm.shutdown, 10.0)
        except BaseException:  # noqa: BLE001
            pass


@pytest.fixture
def env():
    e = Env()
    yield e
    e.close()


class FakeRegistered:
    """Готовый объект протокола ``OrderedExecutor`` для ``register``: считает вызовы закрытия."""

    name = "pm-gate"

    def __init__(self) -> None:
        self.request_stop_calls = 0
        self.join_until_calls = 0

    def submit(self, action, key, reply, *, inline_if_idle: bool = False) -> bool:
        reply(action())
        return False

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def join_until(self, deadline: float) -> bool:
        self.join_until_calls += 1
        return True

    def shutdown(self, deadline: float) -> bool:
        self.request_stop()
        return self.join_until(deadline)


# ---------------------------------------------------------------------------
# R1
# ---------------------------------------------------------------------------


def test_create_from_spec_returns_working_ordered_executor(env):
    """R1: ``create("io", {"kind": "keyed", "serial": True})`` -> рабочий ``OrderedExecutor``, ``get`` тот же объект."""
    from multiprocess_framework.modules.worker_module.interfaces import OrderedExecutor

    mgr = env.manager()
    ex = mgr.create("io", {"kind": "keyed", "serial": True})

    assert isinstance(ex, OrderedExecutor)
    assert mgr.get("io") is ex

    marks: dict[str, float] = {}
    threads: dict[str, str] = {}
    done = {"a": threading.Event(), "b": threading.Event()}

    def make_op(tag: str) -> Callable[[], Any]:
        def op() -> dict:
            marks[f"start_{tag}"] = time.perf_counter()
            threads[tag] = threading.current_thread().name
            time.sleep(0.3)
            marks[f"end_{tag}"] = time.perf_counter()
            return {"success": True, "tag": tag}

        return op

    ex.submit(make_op("a"), frozenset({"a"}), lambda r: done["a"].set())
    ex.submit(make_op("b"), frozenset({"b"}), lambda r: done["b"].set())

    assert done["a"].wait(5.0), "операция a не ответила за 5 с"
    assert done["b"].wait(5.0), "операция b не ответила за 5 с"
    assert marks["start_b"] >= marks["end_a"], "serial=True: b не вправе начаться до конца a"
    assert threads == {"a": "t_keyed-io-0", "b": "t_keyed-io-0"}


# ---------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------


def test_load_config_skips_bad_entries_creates_neighbours(env):
    """R2: неверные записи секции пропущены с ERROR (имя без входного значения), соседняя создана."""
    mgr = env.manager()
    section = {
        "bad": {"kind": "keyed", "max_workerz": 2},
        "bad2": {"kind": "fifo"},
        "good": {"kind": "keyed", "max_workers": 2},
    }

    created = mgr.load_config(section)

    assert created == ["good"]
    assert mgr.names() == ["good"]
    assert list(mgr.describe()["executors"]) == ["good"]

    errors = env.log.at("error")
    assert len(errors) == 2, f"ожидали ровно 2 записи ERROR, получили {errors!r}"
    with_bad2 = [e for e in errors if "bad2" in e]
    only_bad = [e for e in errors if "bad" in e and "bad2" not in e]
    assert len(with_bad2) == 1, f"запись про 'bad2': {errors!r}"
    assert len(only_bad) == 1, f"запись про 'bad': {errors!r}"
    for rec in errors:
        assert "fifo" not in rec, f"входное значение протекло в ERROR: {rec!r}"

    with pytest.raises(ValueError):
        mgr.create("good")


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------


def test_registered_object_routed_not_owned(env):
    """R3: ``register`` - только маршрутизация по имени; закрытие области объект не трогает."""
    mgr = env.manager(scope_budget_s=1.0)
    fake = FakeRegistered()

    mgr.register("gate", fake)

    assert mgr.get("gate") is fake
    run_bounded(env.scope.close, 10.0)
    assert fake.request_stop_calls == 0
    assert fake.join_until_calls == 0
    run_bounded(mgr.shutdown, 10.0)
    assert fake.request_stop_calls == 0, "shutdown менеджера не вправе закрывать зарегистрированный объект"
    assert fake.join_until_calls == 0

    with pytest.raises(TypeError):
        mgr.register("x", object())
    with pytest.raises(ValueError):
        mgr.register("gate", fake)
    assert mgr.names() == ["gate"], "отказ register не оставляет резерва имени"


# ---------------------------------------------------------------------------
# R4
# ---------------------------------------------------------------------------


def test_scope_close_uses_one_deadline_for_all_executors(env):
    """R4: закрытие области с ``budget_s=0.5`` - один общий срок на оба исполнителя, оба в незакрытых."""
    mgr = env.manager(scope_budget_s=5.0)
    release = threading.Event()
    started = {"alpha": threading.Event(), "beta": threading.Event()}
    replied = threading.Event()

    for name in ("alpha", "beta"):
        ex = mgr.create(name, {"serial": True})

        def op(name: str = name) -> dict:
            started[name].set()
            release.wait(2.0)
            return {"success": True}

        ex.submit(op, frozenset({"k"}), lambda r: replied.set())

    try:
        assert started["alpha"].wait(5.0) and started["beta"].wait(5.0), "операции не начались"

        t0 = time.perf_counter()
        report = run_bounded(lambda: env.scope.close(budget_s=0.5), 10.0)
        elapsed = time.perf_counter() - t0

        assert elapsed <= 0.8, f"закрытие заняло {elapsed:.2f} с: срок не общий (сумма ожиданий >= 1.0)"
        assert any("alpha" in s for s in report.survivors), report.survivors
        assert any("beta" in s for s in report.survivors), report.survivors
    finally:
        release.set()


# ---------------------------------------------------------------------------
# R5
# ---------------------------------------------------------------------------


def test_close_from_own_worker_does_not_wait(env):
    """R5: ``shutdown()`` менеджера со своего рабочего не ждёт; ``is_executor_thread`` различает потоки."""
    mgr = env.manager(scope_budget_s=2.0)
    ex = mgr.create("x", {"serial": True})
    mgr.register("gate", FakeRegistered())

    seen: dict[str, Any] = {}
    done = threading.Event()

    def op() -> dict:
        seen["inside"] = mgr.is_executor_thread("x")
        t0 = time.perf_counter()
        mgr.shutdown()
        seen["elapsed"] = time.perf_counter() - t0
        return {"success": True}

    ex.submit(op, frozenset({"k"}), lambda r: done.set())

    assert done.wait(10.0), "операция не ответила за 10 с"
    assert seen["elapsed"] <= 0.3, f"shutdown со своего рабочего ждал {seen['elapsed']:.2f} с"
    assert seen["inside"] is True
    assert mgr.is_executor_thread("x") is False, "на главном потоке признак должен быть False"
    assert mgr.is_executor_thread("gate") is False, "зарегистрированный объект - не поток исполнителя"
    warns = [w for w in env.log.at("warning") if "'x'" in w]
    assert warns, f"нет WARNING с именем 'x': {env.log.at('warning')!r}"
