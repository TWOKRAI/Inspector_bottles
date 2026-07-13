"""Тесты WorkerPoolExecutor — примитив пула поверх worker_module (C6e).

Покрывает: реальное использование worker_module; стоп-механику (cancel истёкших
задач, BaseException-паритет, изоляция экземпляров на общем manager); submit/
collect/resize; маскировку timeout. Контракт-совместимость с прежним
ChainThreadPool — в test_thread_pool.py (без правки ожиданий).
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.chain_module.thread_pool.worker_pool_executor import (
    WorkerPoolExecutor,
)

from .conftest import BrightenOperation, FailingOperation, SlowOp, make_step


@pytest.fixture
def executor():
    ex = WorkerPoolExecutor(max_workers=3, step_timeout=5.0)
    yield ex
    ex.shutdown()


class TestUsesWorkerModule:
    """Пул реально стоит на worker_module — акцепт «chain использует пул worker_module»."""

    def test_creates_n_worker_module_workers(self, executor):
        # N воркеров зарегистрированы в WorkerManager (имена уникальны на экземпляр)
        assert len(executor._worker_names) == 3
        registered = executor._worker_manager.list_workers()
        for name in executor._worker_names:
            assert name in registered

    def test_prod_size_pool_executes(self, frame):
        """Прод-значение N (>1) реально исполняет параллельный бандл."""
        ex = WorkerPoolExecutor(max_workers=4, step_timeout=5.0)
        try:
            assert len(ex._worker_names) == 4
            steps = [make_step(f"n{i}", BrightenOperation(i)) for i in range(4)]
            handles = ex.submit_bundle(steps, frame, context=None)
            results = ex.collect_results(handles, steps, timeout=5.0)
            means = sorted(v.mean() for _, v in results)
            assert means == pytest.approx([0.0, 1.0, 2.0, 3.0])
        finally:
            ex.shutdown()

    def test_shutdown_stops_and_unregisters_workers(self, executor):
        names = list(executor._worker_names)
        executor.shutdown()
        registered = executor._worker_manager.list_workers()
        for name in names:
            assert name not in registered
        assert executor._worker_names == []


class TestStopMechanics:
    """H1/H2/H3/M1 — гарантии, которые прежний stdlib-пул давал бесплатно."""

    def test_expired_task_is_cancelled_not_executed(self, frame):
        """H1: истёкшая по timeout задача НЕ исполняется позже (нет контаминации)."""
        ex = WorkerPoolExecutor(max_workers=1, step_timeout=5.0)
        gate = threading.Event()
        ran: list[int] = []

        class Blocker:
            def execute(self, d, c):
                gate.wait(5)
                return d

            def configure(self, p):
                pass

        class Spy:
            def execute(self, d, c):
                ran.append(1)
                return d

            def configure(self, p):
                pass

        try:
            # Единственный воркер занят блокером
            ex.submit(Blocker(), frame.copy(), None)
            time.sleep(0.15)  # воркер точно забрал блокер
            spy_step = make_step("spy", Spy())
            handles = ex.submit_bundle([spy_step], frame, None)  # в очереди за блокером
            results = ex.collect_results(handles, [spy_step], timeout=0.1)  # timeout → cancel
            assert isinstance(results[0][1], TimeoutError)
            gate.set()  # освободить воркер
            time.sleep(0.3)  # дать воркеру шанс достать spy (должен no-op)
        finally:
            gate.set()
            ex.shutdown()
        assert ran == []  # spy отменён — не исполнился

    def test_baseexception_keeps_worker_alive(self, frame):
        """H2: BaseException из операции → result() re-raise, воркер жив."""

        class MyBase(BaseException):
            pass

        class BaseExcOp:
            def execute(self, d, c):
                raise MyBase("boom")

            def configure(self, p):
                pass

        ex = WorkerPoolExecutor(max_workers=1, step_timeout=5.0)
        try:
            s1 = make_step("b", BaseExcOp())
            h1 = ex.submit_bundle([s1], frame, None)
            _, v1 = ex.collect_results(h1, [s1], timeout=3.0)[0]
            assert isinstance(v1, MyBase)  # НЕ None-как-успех
            # Тот же (единственный) воркер жив → следующая задача исполняется
            s2 = make_step("ok", BrightenOperation(9))
            h2 = ex.submit_bundle([s2], frame, None)
            _, v2 = ex.collect_results(h2, [s2], timeout=3.0)[0]
            assert v2.mean() == pytest.approx(9.0)
        finally:
            ex.shutdown()

    def test_two_executors_share_manager_isolated(self, frame):
        """H3: два пула на общем WorkerManager сосуществуют, shutdown одного не сносит другой."""
        mgr = WorkerManager(manager_name="SharedPoolMgr")
        mgr.initialize()
        ex1 = WorkerPoolExecutor(max_workers=2, worker_manager=mgr)
        ex2 = WorkerPoolExecutor(max_workers=3, worker_manager=mgr)
        try:
            assert len(ex1._worker_names) == 2
            assert len(ex2._worker_names) == 3
            assert set(ex1._worker_names).isdisjoint(ex2._worker_names)  # уникальные имена
            registered = mgr.list_workers()
            for n in ex1._worker_names + ex2._worker_names:
                assert n in registered

            ex1.shutdown()  # owns_manager=False → сносит ТОЛЬКО свои
            registered_after = mgr.list_workers()
            for n in ex2._worker_names:
                assert n in registered_after  # ex2 цел

            step = make_step("n", BrightenOperation(4))
            handles = ex2.submit_bundle([step], frame, None)
            _, v = ex2.collect_results(handles, [step], timeout=5.0)[0]
            assert v.mean() == pytest.approx(4.0)  # ex2 исполняет
        finally:
            ex2.shutdown()
            mgr.shutdown()

    def test_create_worker_failure_is_loud(self):
        """H3: create_worker вернул False → RuntimeError (не тихий пустой пул)."""

        class _FailingMgr:
            def initialize(self):
                return True

            def create_worker(self, *a, **k):
                return False

            def remove_worker(self, *a, **k):
                return True

            def shutdown(self):
                return True

        with pytest.raises(RuntimeError):
            WorkerPoolExecutor(max_workers=1, worker_manager=_FailingMgr())

    def test_submit_after_shutdown_raises(self, frame):
        """M1: submit после shutdown → RuntimeError (паритет со старым пулом)."""
        ex = WorkerPoolExecutor(max_workers=1)
        ex.shutdown()
        with pytest.raises(RuntimeError):
            ex.submit(BrightenOperation(1), frame, None)

    def test_shutdown_wait_drains_full_tail(self):
        """Edge-1: shutdown(wait=True) доисполняет ВЕСЬ хвост, не N задач.

        stop_worker ставит stop_event немедленно (worker_lifecycle.py:135) → без
        ожидания опустошения очереди воркер выходит после ТЕКУЩЕЙ задачи, бросая
        хвост >N. Паритет ThreadPoolExecutor.shutdown(wait=True) — доработать всё.
        """

        class Return:
            def __init__(self, delay: float, val: int):
                self.delay = delay
                self.val = val

            def execute(self, d, c):
                time.sleep(self.delay)
                return self.val

            def configure(self, p):
                pass

        ex = WorkerPoolExecutor(max_workers=2, step_timeout=5.0)
        handles = [ex.submit(Return(0.05, i), None, None) for i in range(6)]  # 6 > 2N
        ex.shutdown(wait=True)
        for i, h in enumerate(handles):
            assert h._event.is_set(), f"handle {i} не завершён (хвост брошен)"
            assert h.result(timeout=0) == i

    def test_orphan_sentinel_reclaimed_on_resize(self, frame):
        """Edge-2: осиротевший сентинел не должен пережить resize и убить нового воркера.

        Зомби после join-таймаута выходит по stop_event, не потребив свой сентинел →
        сентинел остаётся в общей очереди → новый воркер хватает его и умирает.
        """
        ex = WorkerPoolExecutor(max_workers=2, step_timeout=5.0)
        try:
            ex._in_queue.put(None)  # симулируем осиротевший сентинел
            ex.resize(2)

            # Барьер на 2 → проходит ТОЛЬКО если оба воркера нового поколения живы
            barrier = threading.Barrier(2, timeout=3)
            done: list[int] = []

            class BarrierOp:
                def execute(self, d, c):
                    barrier.wait()
                    done.append(1)
                    return d

                def configure(self, p):
                    pass

            steps = [make_step(f"n{i}", BarrierOp()) for i in range(2)]
            handles = ex.submit_bundle(steps, frame, None)
            results = ex.collect_results(handles, steps, timeout=4.0)
            assert all(not isinstance(v, Exception) for _, v in results)
            assert len(done) == 2  # оба воркера дошли до барьера
        finally:
            ex.shutdown()


class TestSubmitCollect:
    def test_submit_single_result(self, executor, frame):
        step = make_step("n1", BrightenOperation(7))
        handle = executor.submit(step.operation, frame.copy(), None)
        assert handle.result(timeout=5).mean() == pytest.approx(7.0)

    def test_collect_exception(self, executor, frame):
        step = make_step("n1", FailingOperation())
        handles = executor.submit_bundle([step], frame, None)
        _, value = executor.collect_results(handles, [step], timeout=5)[0]
        assert isinstance(value, Exception)

    def test_collect_pool_timeout(self, executor, frame):
        step = make_step("slow", SlowOp(10))
        handles = executor.submit_bundle([step], frame, None)
        _, value = executor.collect_results(handles, [step], timeout=0.05)[0]
        assert isinstance(value, TimeoutError)

    def test_business_timeout_not_masked(self, executor, frame):
        """M2: TimeoutError из операции не маскируется под timeout пула."""

        class BizTimeout:
            def execute(self, d, c):
                raise TimeoutError("business-specific")

            def configure(self, p):
                pass

        step = make_step("biz", BizTimeout())
        handles = executor.submit_bundle([step], frame, None)
        t0 = time.monotonic()
        _, value = executor.collect_results(handles, [step], timeout=5.0)[0]
        dt = time.monotonic() - t0
        assert isinstance(value, TimeoutError)
        assert "business-specific" in str(value)  # не «превысила timeout пула»
        assert dt < 1.0  # вернулось сразу, не после step_timeout


class TestResize:
    def test_resize_recreates_pool(self, executor, frame):
        executor.resize(1)
        assert executor.max_workers == 1
        assert len(executor._worker_names) == 1
        step = make_step("n1", BrightenOperation(3))
        handles = executor.submit_bundle([step], frame, None)
        _, value = executor.collect_results(handles, [step], timeout=5)[0]
        assert value.mean() == pytest.approx(3.0)
