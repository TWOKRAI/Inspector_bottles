# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.9m: ``ExecutorManager`` (H1, H3, H5, H6).

Гонки, повторный вход, порядок закрытия. Каждый блокирующий вызов - в daemon-потоке с дедлайном
``join``; ожидания - литералы. Исполнители - настоящие, с настоящим ``WorkerManager``; область -
настоящая (``base_manager.open_scope``). H2, H4, H7, H8 - в
``process_module/tests/test_process_executors_acceptance.py`` (нужен настоящий ``ProcessModule``).
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager


def bounded(fn: Callable[[], Any], timeout: float = 10.0) -> Any:
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


def alive_keyed(prefix: str) -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith(prefix) and t.is_alive()]


def wait_gone(prefix: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive_keyed(prefix):
            return True
        time.sleep(0.01)
    return not alive_keyed(prefix)


class Registered:
    """Готовый объект ``OrderedExecutor`` для ``register``."""

    def submit(self, action, key, reply, *, inline_if_idle: bool = False) -> bool:
        reply(action())
        return False

    def request_stop(self) -> None:
        return None

    def join_until(self, deadline: float) -> bool:
        return True

    def shutdown(self, deadline: float) -> bool:
        return True


@pytest.fixture
def wm():
    manager = WorkerManager(manager_name="h", process=None)
    assert manager.initialize() is True
    yield manager
    bounded(manager.shutdown, 10.0)


# ---------------------------------------------------------------------------
# H1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("with_scope", [False, True], ids=["unowned", "scope"])
def test_h1_create_races_shutdown(wm, with_scope):
    """H1: ``create`` на потоке A параллельно ``shutdown()`` на B (x50): создан и остановлен, либо ``RuntimeError``."""
    created = 0
    refused = 0
    for i in range(50):
        name = f"io{i}"
        mgr = ExecutorManager(f"h_exec{i}", worker_manager=wm)
        assert mgr.initialize() is True
        if with_scope:
            mgr.attach_scope(open_scope(f"h/exec{i}", budget_s=2.0))
        barrier = threading.Barrier(2)
        outcome: dict[str, Any] = {}

        def creator(mgr=mgr, name=name, outcome=outcome, barrier=barrier) -> None:
            barrier.wait(5.0)
            try:
                mgr.create(name, {"max_workers": 2})
                outcome["created"] = True
            except RuntimeError as exc:
                outcome["refused"] = exc

        def closer(mgr=mgr, barrier=barrier) -> None:
            barrier.wait(5.0)
            mgr.shutdown()

        threads = [
            threading.Thread(target=creator, daemon=True, name=f"h1-create-{i}"),
            threading.Thread(target=closer, daemon=True, name=f"h1-close-{i}"),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10.0)
        assert not any(t.is_alive() for t in threads), f"итерация {i}: зависание"
        assert len(outcome) == 1, f"итерация {i}: ожидали ровно один исход, получили {outcome!r}"

        if "refused" in outcome:
            refused += 1
            assert name not in mgr.names(), f"итерация {i}: имя осталось после RuntimeError"
            assert mgr.get(name) is None
        else:
            created += 1
        assert wait_gone(f"h_keyed-{name}-", 2.0), f"итерация {i}: живые потоки {alive_keyed('h_keyed-')}"

    assert created + refused == 50
    assert wait_gone("h_keyed-", 2.0), alive_keyed("h_keyed-")


# ---------------------------------------------------------------------------
# H3
# ---------------------------------------------------------------------------


def test_h3_stop_by_owner_then_scope_close_is_idempotent(wm):
    """H3 (PM-образно): ``request_stop`` + ``join_until`` исполнителя напрямую, затем закрытие области - мгновенно."""
    mgr = ExecutorManager("h_exec", worker_manager=wm)
    assert mgr.initialize() is True
    scope = open_scope("h/exec", budget_s=2.0)
    mgr.attach_scope(scope)
    ex = mgr.create("pm", {"serial": True})

    replies: Counter[str] = Counter()
    results: dict[str, Any] = {}
    lock = threading.Lock()
    started = threading.Event()

    def make(tag: str) -> Callable[[], Any]:
        def op() -> dict:
            if tag == "op0":
                started.set()
                time.sleep(0.2)
            return {"success": True, "tag": tag}

        return op

    def make_reply(tag: str) -> Callable[[Any], None]:
        def reply(result: Any) -> None:
            with lock:
                replies[tag] += 1
                results[tag] = result

        return reply

    for tag in ("op0", "op1", "op2", "op3"):
        ex.submit(make(tag), frozenset({"k"}), make_reply(tag))
        if tag == "op0":
            assert started.wait(5.0), "op0 не началась"

    ex.request_stop()
    assert ex.join_until(time.monotonic() + 1.0) is True

    t0 = time.perf_counter()
    report = bounded(scope.close, 10.0)
    elapsed = time.perf_counter() - t0
    assert elapsed <= 0.05, f"закрытие области после остановки владельцем заняло {elapsed:.3f} с"
    assert not report.survivors, report.survivors
    assert dict(replies) == {"op0": 1, "op1": 1, "op2": 1, "op3": 1}, dict(replies)
    assert results["op0"] == {"success": True, "tag": "op0"}
    for tag in ("op1", "op2", "op3"):
        assert results[tag] == {"success": False, "error": "system_stopping"}, results[tag]
    bounded(mgr.shutdown, 10.0)


def test_h3_executor_created_before_attach_scope_is_closed_by_shutdown(wm):
    """H3 (без области): ``create`` до ``attach_scope`` - ``_on_shutdown`` закрывает ``_unowned`` всегда."""
    mgr = ExecutorManager("h_exec_late", worker_manager=wm)
    assert mgr.initialize() is True
    mgr.create("late", {"max_workers": 2})
    assert len(alive_keyed("h_keyed-late-")) == 2, alive_keyed("h_keyed-late-")
    assert mgr.describe()["executors"]["late"]["owned"] is False

    mgr.attach_scope(open_scope("h/exec-late", budget_s=2.0))
    assert bounded(mgr.shutdown, 10.0) is True
    assert wait_gone("h_keyed-late-", 2.0), alive_keyed("h_keyed-late-")


# ---------------------------------------------------------------------------
# H5
# ---------------------------------------------------------------------------


def test_h5_describe_parallel_with_create_and_register(wm):
    """H5: ``describe()`` в цикле на A, 200 ``register`` + 10 ``create`` на B (старт по Barrier, x5) - 0 исключений."""
    for rnd in range(5):
        mgr = ExecutorManager(f"h_exec_desc{rnd}", worker_manager=wm)
        assert mgr.initialize() is True
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)
        writer_done = threading.Event()
        describes = 0

        def describer(mgr=mgr, errors=errors, barrier=barrier, writer_done=writer_done) -> None:
            nonlocal describes
            try:
                barrier.wait(5.0)
                while not writer_done.is_set():
                    snapshot = mgr.describe()
                    assert isinstance(snapshot["executors"], dict)
                    describes += 1
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def writer(mgr=mgr, errors=errors, barrier=barrier, writer_done=writer_done, rnd=rnd) -> None:
            try:
                barrier.wait(5.0)
                for i in range(200):
                    mgr.register(f"r{i}", Registered())
                    if i % 20 == 0:
                        mgr.create(f"c{rnd}x{i}", {"serial": True})
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                writer_done.set()

        threads = [
            threading.Thread(target=describer, daemon=True, name="h5-describe"),
            threading.Thread(target=writer, daemon=True, name="h5-write"),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30.0)
        assert not any(t.is_alive() for t in threads), f"раунд {rnd}: зависание"
        assert errors == [], f"раунд {rnd}: {errors!r}"
        assert describes > 0
        final = mgr.describe()["executors"]
        assert len(final) == 210
        assert final["r0"]["kind"] == "registered" and final[f"c{rnd}x0"]["kind"] == "keyed"
        bounded(mgr.shutdown, 10.0)


# ---------------------------------------------------------------------------
# H6
# ---------------------------------------------------------------------------


def test_h6_name_collision_keeps_first_owner(wm):
    """H6: ``register`` под именем созданного - ``ValueError``, ``get`` отдаёт созданный; и наоборот."""
    mgr = ExecutorManager("h_exec_names", worker_manager=wm)
    assert mgr.initialize() is True
    created = mgr.create("io", {"serial": True})
    other = Registered()

    with pytest.raises(ValueError):
        mgr.register("io", other)
    assert mgr.get("io") is created

    mgr.register("gate", other)
    with pytest.raises(ValueError):
        mgr.create("gate")
    assert mgr.get("gate") is other

    with pytest.raises(ValueError):
        mgr.create("io")
    assert mgr.get("io") is created
    assert mgr.names() == ["io", "gate"]
    bounded(mgr.shutdown, 10.0)


def test_h6_failed_create_releases_name(wm):
    """H6: провал создания (схема, конструктор) снимает резерв имени."""
    mgr = ExecutorManager("h_exec_fail", worker_manager=wm)
    assert mgr.initialize() is True

    with pytest.raises(ValueError):
        mgr.create("bad", {"max_workers": 0})
    assert mgr.names() == [] and mgr.get("bad") is None

    # Конструктор KeyedExecutor: воркер "keyed-dup-0" уже занят другим менеджером на том же WorkerManager.
    first = ExecutorManager("h_exec_first", worker_manager=wm)
    assert first.initialize() is True
    first.create("dup", {"serial": True})
    with pytest.raises(ValueError):
        mgr.create("dup", {"serial": True})
    assert mgr.names() == [] and mgr.get("dup") is None

    assert mgr.create("bad") is not None  # имя снова свободно
    bounded(mgr.shutdown, 10.0)
    bounded(first.shutdown, 10.0)


# ---------------------------------------------------------------------------
# H9
# ---------------------------------------------------------------------------


def test_h9_close_between_reservation_and_commit_refused_and_name_released(wm, monkeypatch):
    """H9 (ветка late): закрытие после резерва имени, до записи - ``RuntimeError``, имени нет, рабочие остановлены."""
    from multiprocess_framework.modules.worker_module import executor_manager as module

    mgr = ExecutorManager("h_exec_late2", worker_manager=wm)
    assert mgr.initialize() is True
    real = module.KeyedExecutor

    def closing_factory(*args, **kwargs):
        mgr.shutdown()  # менеджер закрывается, пока имя "y" зарезервировано, а запись ещё не сделана
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "KeyedExecutor", closing_factory)

    with pytest.raises(RuntimeError):
        mgr.create("y", {"max_workers": 2})
    assert "y" not in mgr.names()
    assert mgr.get("y") is None
    assert wait_gone("h_keyed-y-", 2.0), alive_keyed("h_keyed-y-")
    # Резерв снят: имя свободно для register (закрытый менеджер create отвергает раньше проверки имени).
    other = Registered()
    mgr.register("y", other)
    assert mgr.get("y") is other


def test_h9_create_after_shutdown_without_scope_refused(wm):
    """H9: менеджер без области, ``shutdown()``, затем ``create`` - ``RuntimeError``, имени и потоков нет."""
    mgr = ExecutorManager("h_exec_closed", worker_manager=wm)
    assert mgr.initialize() is True
    assert bounded(mgr.shutdown, 10.0) is True

    with pytest.raises(RuntimeError):
        mgr.create("x", {"max_workers": 2})
    assert "x" not in mgr.names()
    assert mgr.get("x") is None
    assert wait_gone("h_keyed-x-", 2.0), alive_keyed("h_keyed-x-")


# ---------------------------------------------------------------------------
# D6: describe() - литералы
# ---------------------------------------------------------------------------


def test_describe_literals_for_created_and_registered(wm):
    """D6: ``unavailable``, поля созданного и зарегистрированного, воркеры."""
    mgr = ExecutorManager("h_exec_d6", worker_manager=wm)
    assert mgr.initialize() is True
    mgr.create("io", {"max_workers": 2})
    mgr.register("gate", Registered())

    snapshot = mgr.describe()

    assert snapshot["unavailable"] == ["pending_depth", "running_keys"]
    assert snapshot["executors"]["gate"] == {"kind": "registered", "source": "code", "type": "Registered"}
    io = snapshot["executors"]["io"]
    for key, value in {
        "kind": "keyed",
        "source": "code",
        "serial": False,
        "max_workers": 2,
        "max_pending": 64,
        "owned": False,
    }.items():
        assert io[key] == value, (key, io)
    assert sorted(io["workers"]) == ["keyed-io-0", "keyed-io-1"]
    assert all(w["is_alive"] is True for w in io["workers"].values()), io["workers"]
    bounded(mgr.shutdown, 10.0)


def test_describe_removed_worker_is_absent(wm):
    """D6: рабочий снят напрямую (в обход IPC-защиты) - ``{"is_alive": False, "status": "absent"}``."""
    mgr = ExecutorManager("h_exec_absent", worker_manager=wm)
    assert mgr.initialize() is True
    mgr.create("io", {"max_workers": 2})

    assert bounded(lambda: wm.remove_worker("keyed-io-1"), 10.0) is True

    workers = mgr.describe()["executors"]["io"]["workers"]
    assert workers["keyed-io-1"] == {"is_alive": False, "status": "absent"}
    bounded(mgr.shutdown, 10.0)


# ---------------------------------------------------------------------------
# Сбой между резервом и владением
# ---------------------------------------------------------------------------


class _NoManagerName:
    """``worker_manager`` без ``manager_name``: имена потоков посчитать нельзя."""

    def __init__(self, real: Any) -> None:
        self._real = real

    def __getattr__(self, attr: str) -> Any:
        if attr == "manager_name":
            raise AttributeError(attr)
        return getattr(self._real, attr)


def test_failure_before_ownership_leaves_no_reservation_and_no_threads(wm):
    """Исключение при подготовке создания: имя не занято, исполнитель без владельца не остался."""
    mgr = ExecutorManager("h_exec_noname", worker_manager=_NoManagerName(wm))
    assert mgr.initialize() is True

    with pytest.raises(AttributeError):
        mgr.create("io")
    with pytest.raises(AttributeError):  # не "имя уже занято" (ValueError)
        mgr.create("io")
    assert mgr.names() == [] and mgr.get("io") is None
    assert alive_keyed("h_keyed-io-") == [], alive_keyed("h_keyed-io-")
