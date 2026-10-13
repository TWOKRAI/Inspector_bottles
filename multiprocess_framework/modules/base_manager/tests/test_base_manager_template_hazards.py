"""Авторские hazard-тесты Task 1.2b-1: шаблон ``BaseManager.shutdown()`` и ``scope``.

Гонки, сроки второго вызова, подделка ``IScope`` (G-14), поток поддерева области,
pickle по четырём путям ``__getstate__`` и пригодность 32 классов фреймворка как
ключа слабого словаря (weakref + hash). Ожидаемые значения — литералы брифа;
всё, что может зависнуть, идёт в daemon-потоке со сроком.
"""

from __future__ import annotations

import gc
import importlib
import logging
import pickle
import threading
import time
import uuid
import weakref

import pytest

from multiprocess_framework.modules.base_manager import ObservableMixin, open_scope, unclosed_roots
from multiprocess_framework.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.modules.shared_resources_module.core.shared_resources_manager import (
    SharedResourcesManager,
)

from .test_base_manager import ConcreteManager

DEADLINE_S = 15.0
LOGGER_NAME = "multiprocess_framework.modules.base_manager.core.base_manager"


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


class Counter:
    def __init__(self) -> None:
        self.n = 0
        self._lock = threading.Lock()

    def inc(self) -> None:
        with self._lock:
            self.n += 1


class HookManager(BaseManager):
    """Тестовый подкласс: определяет ``_on_shutdown`` (не ``shutdown``)."""

    _ON_SHUTDOWN_WAIT_S = 0.0  # Task 1.2b-2: тесты мерят только член области (Н-6)

    def __init__(self, name: str, hook=None) -> None:
        super().__init__(name)
        self._hook = hook

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        return True if self._hook is None else self._hook(self)


class MixinManager(BaseManager, ObservableMixin):
    """Наследник ``ObservableMixin``: pickle идёт через ``ObservableMixin.__getstate__``."""

    def __init__(self, name: str) -> None:
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers={})

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        return True


class FakeScope:
    """Подделка ``IScope`` (не ``Scope``): ни ``_is_subtree_thread``, ни ``budget_s``."""

    def __init__(self, path: str = "fake/scope") -> None:
        self.path = path
        self.closed = False
        self.close_calls = 0

    def close(self, budget_s=None, *, deadline=None):
        self.close_calls += 1
        self.closed = True
        return None


@pytest.fixture
def make_root():
    """Настоящие корни ``t02…``; все закрываются в teardown (G3)."""
    roots: list = []

    def factory(budget_s: float = 2.0, kill_reserve_s: float = 0.0):
        root = open_scope(f"t02{uuid.uuid4().hex[:10]}", budget_s=budget_s, kill_reserve_s=kill_reserve_s)
        roots.append(root)
        return root

    yield factory
    for root in roots:
        try:
            root.close()
        except Exception:  # noqa: BLE001 - уборка, не предмет теста
            pass


def _second_call_while_first_blocked(mgr: HookManager, gate: threading.Event, entered: threading.Event):
    """Первый вызов висит в ``_on_shutdown`` на ``gate``; вернуть (поток первого, итог второго)."""
    box: dict = {}

    def first() -> None:
        box["first"] = mgr.shutdown()

    a = threading.Thread(target=first, daemon=True, name="first_call")
    a.start()
    assert entered.wait(DEADLINE_S), "первый вызов не дошёл до _on_shutdown"
    second = call_bounded(mgr.shutdown, DEADLINE_S)
    return a, box, second


# ---------------------------------------------------------------------------
# G-14: подделка IScope
# ---------------------------------------------------------------------------


def test_fake_iscope_shutdown_works_without_attribute_error() -> None:
    fake = FakeScope()
    seen: dict = {}

    def hook(mgr) -> bool:
        seen["closed_then"] = mgr.scope.closed
        return True

    mgr = HookManager("fake_mgr", hook)
    mgr.attach_scope(fake)
    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done, "shutdown() завис"
    assert error is None, repr(error)
    assert result is True
    assert fake.close_calls == 1
    assert seen["closed_then"] is True


def test_fake_iscope_second_call_waits_5s_then_false_and_logs(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    entered, gate = threading.Event(), threading.Event()

    def hook(_mgr) -> bool:
        entered.set()
        gate.wait(DEADLINE_S)
        return True

    mgr = HookManager("fake_wait_mgr", hook)
    mgr.attach_scope(FakeScope())
    try:
        a, box, (done, result, error, elapsed) = _second_call_while_first_blocked(mgr, gate, entered)
        assert done, "второй вызов завис дольше срока"
        assert error is None, repr(error)
        assert result is False
        assert 4.5 <= elapsed < 8.0, f"второй вызов ждал {elapsed:.3f} с, ожидалось 5,0 с"
    finally:
        gate.set()
    a.join(DEADLINE_S)
    assert box["first"] is True
    expected = "shutdown fake_wait_mgr: первый вызов не завершился за 5 с — второй вызов вернул False"
    messages = [r.getMessage() for r in caplog.records]
    assert sum(expected in m for m in messages) == 1, messages
    assert mgr.shutdown() is True, "после завершения первого — его результат"


def test_no_scope_second_call_waits_5s_then_false() -> None:
    entered, gate = threading.Event(), threading.Event()

    def hook(_mgr) -> bool:
        entered.set()
        gate.wait(DEADLINE_S)
        return True

    mgr = HookManager("noscope_wait_mgr", hook)
    try:
        a, box, (done, result, error, elapsed) = _second_call_while_first_blocked(mgr, gate, entered)
        assert done and error is None, repr(error)
        assert result is False
        assert 4.5 <= elapsed < 8.0, f"второй вызов ждал {elapsed:.3f} с, ожидалось 5,0 с"
    finally:
        gate.set()
    a.join(DEADLINE_S)
    assert box["first"] is True


def test_real_scope_second_call_waits_budget_plus_reserve(make_root, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    entered, gate = threading.Event(), threading.Event()

    def hook(_mgr) -> bool:
        entered.set()
        gate.wait(DEADLINE_S)
        return True

    mgr = HookManager("budget_wait_mgr", hook)
    mgr.attach_scope(make_root(budget_s=0.3, kill_reserve_s=0.2))
    try:
        # Первый вызов держится до gate (до 15 с) и вернёт True: False второго — только от срока 0,5 с.
        a, box, (done, result, error, elapsed) = _second_call_while_first_blocked(mgr, gate, entered)
        assert done, "второй вызов не вернулся: у настоящего Scope нет срока ожидания"
        assert error is None, repr(error)
        assert result is False
        assert 0.5 <= elapsed < 1.5, f"второй вызов ждал {elapsed:.3f} с, ожидалось 0,5 с"
        assert a.is_alive(), "первый вызов должен ещё держаться на gate"
    finally:
        gate.set()
    a.join(DEADLINE_S)
    assert box["first"] is True
    expected = "shutdown budget_wait_mgr: первый вызов не завершился за 0.5 с — второй вызов вернул False"
    assert any(expected in r.getMessage() for r in caplog.records), [r.getMessage() for r in caplog.records]


# ---------------------------------------------------------------------------
# Гонки
# ---------------------------------------------------------------------------


def test_race_many_concurrent_shutdowns_call_on_shutdown_once() -> None:
    for i in range(30):
        counter = Counter()

        def hook(_mgr, counter=counter) -> bool:
            counter.inc()
            time.sleep(0.02)
            return True

        mgr = HookManager(f"race_{i}", hook)
        barrier = threading.Barrier(8)
        results: list = []
        lock = threading.Lock()

        def worker(mgr=mgr, barrier=barrier, results=results, lock=lock) -> None:
            barrier.wait(DEADLINE_S)
            r = mgr.shutdown()
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(DEADLINE_S)
        assert not any(t.is_alive() for t in threads), "shutdown() завис"
        assert counter.n == 1, f"итерация {i}: _on_shutdown вызван {counter.n} раз"
        assert results == [True] * 8, f"итерация {i}: {results}"


def test_race_concurrent_attach_scope_exactly_one_wins() -> None:
    for i in range(50):
        mgr = HookManager(f"attach_race_{i}")
        fakes = [FakeScope(f"fake/{i}/a"), FakeScope(f"fake/{i}/b")]
        barrier = threading.Barrier(2)
        outcome: list = []
        lock = threading.Lock()

        def worker(fake, mgr=mgr, barrier=barrier, outcome=outcome, lock=lock) -> None:
            barrier.wait(DEADLINE_S)
            try:
                mgr.attach_scope(fake)
                res = ("ok", fake)
            except RuntimeError:
                res = ("refused", fake)
            with lock:
                outcome.append(res)

        threads = [threading.Thread(target=worker, args=(f,), daemon=True) for f in fakes]
        for t in threads:
            t.start()
        for t in threads:
            t.join(DEADLINE_S)
        kinds = sorted(k for k, _ in outcome)
        assert kinds == ["ok", "refused"], f"итерация {i}: {outcome}"
        winner = next(f for k, f in outcome if k == "ok")
        assert mgr.scope is winner


# ---------------------------------------------------------------------------
# G-11: поток поддерева — первым, до любого останова
# ---------------------------------------------------------------------------


def test_subtree_thread_first_call_false_does_not_start_shutdown(make_root) -> None:
    counter = Counter()
    seen: dict = {}
    called = threading.Event()

    def hook(_mgr) -> bool:
        counter.inc()
        return True

    mgr = HookManager("subtree_mgr", hook)
    root = make_root()
    child = root.child("mgr-scope")
    mgr.attach_scope(child)

    def target(stop_event: threading.Event) -> None:
        t0 = time.monotonic()
        seen["result"] = mgr.shutdown()
        seen["elapsed"] = time.monotonic() - t0
        seen["on_shutdown_calls_then"] = counter.n
        called.set()
        stop_event.wait(DEADLINE_S)

    child.spawn(target, name="t")
    assert called.wait(DEADLINE_S), "поток области не дошёл до shutdown()"
    assert seen["result"] is False
    assert seen["elapsed"] < 1.0, f"вызов из поддерева ждал {seen['elapsed']:.3f} с"
    assert seen["on_shutdown_calls_then"] == 0

    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is True, "останов не должен был начаться из потока поддерева"
    assert counter.n == 1
    assert child.closed is True


# ---------------------------------------------------------------------------
# BaseException в _on_shutdown: ждущие не висят
# ---------------------------------------------------------------------------


def test_base_exception_in_on_shutdown_propagates_and_caches_false() -> None:
    counter = Counter()

    def hook(_mgr) -> bool:
        counter.inc()
        raise KeyboardInterrupt("stop")

    mgr = HookManager("kbi_mgr", hook)
    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done
    assert isinstance(error, KeyboardInterrupt)
    done, result, error, elapsed = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is False
    assert elapsed < 1.0, f"повтор ждал {elapsed:.3f} с"
    assert counter.n == 1


# ---------------------------------------------------------------------------
# G-5: pickle по четырём путям __getstate__
# ---------------------------------------------------------------------------


def _make_concrete():
    return ConcreteManager("pickle_concrete")


def _make_mixin():
    return MixinManager("pickle_mixin")


def _make_srm():
    from multiprocess_framework.modules.shared_resources_module.core.shared_resources_manager import (
        SharedResourcesManager,
    )

    return SharedResourcesManager()


def _make_event_manager():
    from multiprocess_framework.modules.shared_resources_module.events import EventManager

    em = EventManager()
    em.initialize()
    return em


@pytest.mark.parametrize(
    "factory",
    [_make_concrete, _make_mixin, _make_srm, _make_event_manager],
    ids=["ConcreteManager", "ObservableMixin_heir", "SharedResourcesManager", "EventManager"],
)
def test_pickle_with_attached_scope(factory, make_root) -> None:
    mgr = factory()
    scope = make_root()
    mgr.attach_scope(scope)

    restored = pickle.loads(pickle.dumps(mgr))

    assert restored.scope is None
    assert mgr.scope is scope
    other = FakeScope("fake/restored")
    restored.attach_scope(other)
    assert restored.scope is other
    assert mgr.scope is scope


# ---------------------------------------------------------------------------
# weakref + hash: 32 класса фреймворка годятся в ключ слабого словаря
# ---------------------------------------------------------------------------

FRAMEWORK_MANAGER_CLASSES = [
    # 23 класса со своим shutdown (инвентарь 1.2b)
    "multiprocess_framework.modules.chain_module.metrics.latency.LatencyTracker",
    "multiprocess_framework.modules.chain_module.thread_pool.worker_pool_executor.WorkerPoolExecutor",
    "multiprocess_framework.modules.chain_module.worker_pool.dispatcher.WorkerPoolDispatcher",
    "multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager.ChannelRoutingManager",
    "multiprocess_framework.modules.command_module.core.command_manager.CommandManager",
    "multiprocess_framework.modules.config_module.core.config_manager.ConfigManager",
    "multiprocess_framework.modules.console_module.core.console_manager.ConsoleManager",
    "multiprocess_framework.modules.dispatch_module.core.dispatcher.Dispatcher",
    "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendManager",
    "multiprocess_framework.modules.logger_module.core.logger_core.LoggerCore",
    "multiprocess_framework.modules.logger_module.core.logger_manager.LoggerManager",
    "multiprocess_framework.modules.process_manager_module.process.topology_manager.TopologyManager",
    "multiprocess_framework.modules.process_module.core.process_module.ProcessModule",
    "multiprocess_framework.modules.process_module.plugins.manager.PluginManager",
    "multiprocess_framework.modules.registers_module.core.manager.RegistersManager",
    "multiprocess_framework.modules.router_module.core.router_manager.RouterManager",
    "multiprocess_framework.modules.shared_resources_module.core.shared_resources_manager.SharedResourcesManager",
    "multiprocess_framework.modules.shared_resources_module.events.core.manager.EventManager",
    "multiprocess_framework.modules.shared_resources_module.memory.core.manager.MemoryManager",
    "multiprocess_framework.modules.shared_resources_module.queues.core.manager.QueueRegistry",
    "multiprocess_framework.modules.state_store_module.manager.state_store_manager.StateStoreManager",
    "multiprocess_framework.modules.state_store_module.proxy.state_proxy.StateProxy",
    "multiprocess_framework.modules.worker_module.core.worker_manager.WorkerManager",
    # 9 без своего shutdown
    "multiprocess_framework.modules.chain_module.thread_pool.pool.ChainThreadPool",
    "multiprocess_framework.modules.error_module.core.error_manager.ErrorManager",
    "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess",
    "multiprocess_framework.modules.app_module.orchestrator.GenericProcessManagerApp",
    "multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy.GuiStateProxy",
    "multiprocess_framework.modules.statistics_module.observation.observation_manager.ObservationManager",
    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessManagerProcess",
    "multiprocess_framework.modules.frontend_module.bridge.remote_state_proxy.RemoteStateProxy",
    "multiprocess_framework.modules.statistics_module.core.stats_manager.StatsManager",
]


def _load(dotted: str):
    module_name, _, class_name = dotted.rpartition(".")
    assert module_name.startswith("multiprocess_framework."), dotted
    return getattr(importlib.import_module(module_name), class_name)


def test_framework_manager_list_is_32() -> None:
    assert len(FRAMEWORK_MANAGER_CLASSES) == 32
    assert len(set(FRAMEWORK_MANAGER_CLASSES)) == 32


@pytest.mark.parametrize("dotted", FRAMEWORK_MANAGER_CLASSES, ids=lambda d: d.rpartition(".")[2])
def test_framework_manager_has_dict_and_independent_record(dotted: str) -> None:
    cls = _load(dotted)
    assert issubclass(cls, BaseManager)
    # Без __init__: проверяется сам класс (есть __dict__ под запись жизни), не его конструктор.
    obj = cls.__new__(cls)
    twin = cls.__new__(cls)
    assert isinstance(obj.__dict__, dict)
    assert isinstance(twin.__dict__, dict)
    assert obj.scope is None
    assert twin.scope is None
    fake_a = FakeScope(f"fake/{cls.__name__}/a")
    fake_b = FakeScope(f"fake/{cls.__name__}/b")
    obj.attach_scope(fake_a)
    assert twin.scope is None, "области двух экземпляров не должны совпадать"
    twin.attach_scope(fake_b)
    assert obj.scope is fake_a
    assert twin.scope is fake_b


# ---------------------------------------------------------------------------
# CTO (хранение C): брошенный менеджер с областью собирается, G3 видит корень
# ---------------------------------------------------------------------------


class TickManager(BaseManager):
    def initialize(self) -> bool:
        return True

    def tick(self) -> None:
        pass


def test_abandoned_manager_with_scope_is_collected_and_root_seen_abandoned() -> None:
    root_path = f"t02{uuid.uuid4().hex[:10]}"
    m = TickManager("gc_mgr")
    root = open_scope(root_path, budget_s=1.0)
    m.attach_scope(root)
    root.own(m.tick, name="tick")
    ref = weakref.ref(m)
    del m, root
    gc.collect()
    assert ref() is None, "менеджер с областью держится глобальным якорем"
    assert {"path": root_path, "state": "abandoned"} in unclosed_roots()


# ---------------------------------------------------------------------------
# CTO (хранение C): копия после pickle независима от оригинала
# ---------------------------------------------------------------------------

_ON_SHUTDOWN_CALLS: list = []


class CountingMixinManager(BaseManager, ObservableMixin):
    def __init__(self, name: str) -> None:
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers={})

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        _ON_SHUTDOWN_CALLS.append(id(self))
        return True


class CountingSRM(SharedResourcesManager):
    """SRM со своим ``shutdown`` (мягкий режим): шаблон зовётся явно ``BaseManager.shutdown``."""

    def _on_shutdown(self) -> bool:
        _ON_SHUTDOWN_CALLS.append(id(self))
        return True


@pytest.mark.parametrize(
    "factory",
    [lambda: CountingMixinManager("pickle_copy_mixin"), lambda: CountingSRM()],
    ids=["ObservableMixin_heir", "SharedResourcesManager"],
)
def test_pickled_copy_has_independent_shutdown(factory, make_root) -> None:
    _ON_SHUTDOWN_CALLS.clear()
    original = factory()
    original.attach_scope(make_root())
    assert BaseManager.shutdown(original) is True

    restored = pickle.loads(pickle.dumps(original))

    assert restored.scope is None
    done, result, error, elapsed = call_bounded(lambda: BaseManager.shutdown(restored), DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is True
    assert elapsed < 1.0, f"копия ждала {elapsed:.3f} с — состояние оригинала уехало в копию"
    assert BaseManager.shutdown(original) is True
    assert BaseManager.shutdown(restored) is True
    assert len(_ON_SHUTDOWN_CALLS) == 2
    assert _ON_SHUTDOWN_CALLS[0] != _ON_SHUTDOWN_CALLS[1]


# ---------------------------------------------------------------------------
# CTO (путь лога): строки шаблона — только вид
# ---------------------------------------------------------------------------


class RaisingMixinManager(BaseManager, ObservableMixin):
    def __init__(self, name: str) -> None:
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers={})

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        raise RuntimeError("kaboom-mx")


def test_mixin_without_logger_failure_line_exactly_once(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    mgr = RaisingMixinManager("mx_mgr")
    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is False
    expected = "shutdown mx_mgr: _on_shutdown упал: RuntimeError: kaboom-mx"
    messages = [r.getMessage() for r in caplog.records]
    assert sum(expected in m for m in messages) == 1, messages


class WiredRaisingManager(BaseManager, ObservableMixin):
    def __init__(self, name: str, logger_manager) -> None:
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self, managers={"logger": logger_manager})

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        raise RuntimeError("kaboom-pm")


def test_process_logger_counts_failure_line_once() -> None:
    from multiprocess_framework.modules.base_manager.core import base_manager as bm_module
    from multiprocess_framework.modules.process_module import ProcessModule

    proc = ProcessModule("p", config={})
    assert proc.initialize() is True
    try:
        lm = proc.logger_manager
        bm_module._logger.error("прогрев вида")  # ранний буфер вида сливается здесь, не в замере
        before = lm.get_stats()["messages_processed"]
        # Миксин, подключённый к логгеру процесса: слот-дорога _log_error дала бы вторую запись.
        mgr = WiredRaisingManager("pm_fail_mgr", lm)
        assert mgr.shutdown() is False
        after = lm.get_stats()["messages_processed"]
        assert after - before == 1
    finally:
        call_bounded(proc.shutdown, 20.0)


# ---------------------------------------------------------------------------
# Ревью р.1 п.6: решения исполнителя
# ---------------------------------------------------------------------------


class BadScope(FakeScope):
    def close(self, budget_s=None, *, deadline=None):
        self.close_calls += 1
        raise ValueError("close-broke")


def test_scope_close_raising_logs_and_still_calls_on_shutdown(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    counter = Counter()

    def hook(_mgr) -> bool:
        counter.inc()
        return True

    mgr = HookManager("a_mgr", hook)
    bad = BadScope("bad/scope")
    mgr.attach_scope(bad)
    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is True
    assert counter.n == 1
    assert bad.close_calls == 1
    expected = "shutdown a_mgr: scope.close упал: ValueError: close-broke"
    assert any(expected in r.getMessage() for r in caplog.records), [r.getMessage() for r in caplog.records]


def test_attach_scope_none_type_error() -> None:
    mgr = HookManager("c_mgr")
    with pytest.raises(TypeError, match="attach_scope c_mgr: нужна область, получено None"):
        mgr.attach_scope(None)
    assert mgr.scope is None


# ---------------------------------------------------------------------------
# Матрица inj-21: BaseException не оставляет ждущий второй вызов висеть
# ---------------------------------------------------------------------------


def test_waiting_second_call_returns_promptly_after_base_exception() -> None:
    entered, gate = threading.Event(), threading.Event()
    box: dict = {}

    def hook(_mgr) -> bool:
        entered.set()
        gate.wait(DEADLINE_S)
        raise KeyboardInterrupt("stop")

    mgr = HookManager("kbi_wait_mgr", hook)

    def first() -> None:
        try:
            box["first"] = mgr.shutdown()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["first_error"] = exc

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
        assert b.is_alive(), "второй вызов должен ждать первый"
        released_at = time.monotonic()
        gate.set()
        a.join(DEADLINE_S)
        b.join(DEADLINE_S)
    finally:
        gate.set()
    assert not b.is_alive(), "второй вызов завис"
    assert isinstance(box.get("first_error"), KeyboardInterrupt)
    assert box["second"] is False
    waited = box["second_at"] - released_at
    assert waited < 1.0, f"второй вызов вернулся через {waited:.3f} с после BaseException, ожидалось сразу"


# ---------------------------------------------------------------------------
# 1.2b-ki: BaseException в scope.close() не отменяет _on_shutdown()
# ---------------------------------------------------------------------------


class InterruptingScope(FakeScope):
    """Подделка области: ``close()`` пишет «close» в журнал и бросает заданное исключение."""

    def __init__(self, exc: BaseException, journal: list, path: str = "ki/scope") -> None:
        super().__init__(path)
        self._exc = exc
        self._journal = journal

    def close(self, budget_s=None, *, deadline=None):
        self.close_calls += 1
        self._journal.append("close")
        raise self._exc


def _ki_manager(name: str, exc: BaseException, hook_body=None):
    """Менеджер с прерывающей областью; ``hook_body`` — что делает ``_on_shutdown`` после записи в журнал."""
    journal: list = []
    counter = Counter()

    def hook(_mgr) -> bool:
        counter.inc()
        journal.append("on_shutdown")
        return True if hook_body is None else hook_body()

    mgr = HookManager(name, hook)
    scope = InterruptingScope(exc, journal)
    mgr.attach_scope(scope)
    return mgr, scope, journal, counter


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_ki_close_interrupt_still_calls_on_shutdown_once_after_close(exc_type) -> None:
    """K-1: прерывание в close -> _on_shutdown вызван ровно один раз, после close."""
    mgr, scope, journal, counter = _ki_manager("ki1_mgr", exc_type("close-stop"))
    done, _result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done
    assert isinstance(error, exc_type), repr(error)
    assert journal == ["close", "on_shutdown"]
    assert counter.n == 1
    assert scope.close_calls == 1


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_ki_close_interrupt_same_object_propagates(exc_type) -> None:
    """K-2: из shutdown() выходит тот же объект исключения, что бросил close."""
    exc = exc_type("close-stop")
    mgr, _scope, _journal, _counter = _ki_manager("ki2_mgr", exc)
    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done
    assert result is None
    assert error is exc


def test_ki_close_interrupt_caches_false_even_if_on_shutdown_true() -> None:
    """K-3: кэш False при True от _on_shutdown; повтор — False сразу, тело не зовётся снова."""
    mgr, _scope, _journal, counter = _ki_manager("ki3_mgr", KeyboardInterrupt("close-stop"))
    done, _result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done
    assert isinstance(error, KeyboardInterrupt), repr(error)
    assert counter.n == 1
    done, result, error, elapsed = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is False
    assert elapsed < 1.0, f"повтор ждал {elapsed:.3f} с"
    assert counter.n == 1


def test_ki_close_interrupt_logged_exactly_once(caplog) -> None:
    """K-4: строка «scope.close прерван» ровно одна."""
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    mgr, _scope, _journal, _counter = _ki_manager("ki4_mgr", KeyboardInterrupt("close-stop"))
    done, _result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done
    assert isinstance(error, KeyboardInterrupt), repr(error)
    messages = [r.getMessage() for r in caplog.records]
    expected = "shutdown ki4_mgr: scope.close прерван: KeyboardInterrupt: close-stop"
    assert sum(expected in m for m in messages) == 1, messages
    assert not any("scope.close упал" in m for m in messages), messages


def test_ki_on_shutdown_error_after_close_interrupt_keeps_interrupt(caplog) -> None:
    """K-5: RuntimeError в _on_shutdown на этом пути -> наверх KeyboardInterrupt, строка о RuntimeError есть."""
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    def broken() -> bool:
        raise RuntimeError("hook-broke")

    exc = KeyboardInterrupt("close-stop")
    mgr, _scope, journal, counter = _ki_manager("ki5_mgr", exc, broken)
    done, _result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done
    assert error is exc, repr(error)
    assert journal == ["close", "on_shutdown"]
    assert counter.n == 1
    messages = [r.getMessage() for r in caplog.records]
    expected = "shutdown ki5_mgr: _on_shutdown упал: RuntimeError: hook-broke"
    assert sum(expected in m for m in messages) == 1, messages
    done, result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is False


def test_ki_on_shutdown_base_exception_after_close_interrupt_wins() -> None:
    """Правило 4 DESIGN: BaseException самого _on_shutdown уходит наверх, __context__ — исходное; кэш False."""
    hook_exc = SystemExit("hook-exit")

    def exiting() -> bool:
        raise hook_exc

    close_exc = KeyboardInterrupt("close-stop")
    mgr, _scope, journal, counter = _ki_manager("ki6_mgr", close_exc, exiting)
    done, _result, error, _ = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done
    assert error is hook_exc, repr(error)
    assert error.__context__ is close_exc
    assert journal == ["close", "on_shutdown"]
    done, result, error, elapsed = call_bounded(mgr.shutdown, DEADLINE_S)
    assert done and error is None, repr(error)
    assert result is False
    assert elapsed < 1.0, f"повтор ждал {elapsed:.3f} с"
    assert counter.n == 1
