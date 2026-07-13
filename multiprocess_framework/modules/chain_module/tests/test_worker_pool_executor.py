"""Тесты WorkerPoolExecutor — примитив пула поверх worker_module (C6e).

Ключевая проверка задачи: пул физически использует worker_module (N воркеров
через WorkerManager), а не собственный поток-пул. Публичный контракт
(submit/submit_bundle/collect_results/resize/shutdown) покрыт отдельно;
контракт-совместимость с прежним ChainThreadPool — в test_thread_pool.py.
"""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.chain_module.thread_pool.worker_pool_executor import (
    WorkerPoolExecutor,
)

from .conftest import BrightenOperation, FailingOperation, FakeNode, RunnableStep


def make_step(node_id: str, operation=None, on_error: str = "skip") -> RunnableStep:
    node = FakeNode(node_id=node_id)
    op = operation if operation is not None else BrightenOperation(0)
    return RunnableStep(node=node, operation=op, on_error=on_error)


@pytest.fixture
def executor():
    ex = WorkerPoolExecutor(max_workers=3, step_timeout=5.0)
    yield ex
    ex.shutdown()


class TestUsesWorkerModule:
    """Пул реально стоит на worker_module — акцепт задачи «chain использует пул worker_module»."""

    def test_creates_n_worker_module_workers(self, executor):
        # N воркеров зарегистрированы в WorkerManager под именами chain_pool_i
        names = executor._worker_manager.list_workers()
        pool_workers = [n for n in names if n.startswith("chain_pool_")]
        assert len(pool_workers) == 3
        assert set(pool_workers) == {"chain_pool_0", "chain_pool_1", "chain_pool_2"}

    def test_prod_size_pool_executes(self):
        """Прод-значение N (>1) реально исполняет параллельный бандл."""
        ex = WorkerPoolExecutor(max_workers=4, step_timeout=5.0)
        try:
            assert len([n for n in ex._worker_manager.list_workers() if n.startswith("chain_pool_")]) == 4
            steps = [make_step(f"n{i}", BrightenOperation(i)) for i in range(4)]
            import numpy as np

            frame = np.zeros((4, 4), dtype=np.float32)
            handles = ex.submit_bundle(steps, frame, context=None)
            results = ex.collect_results(handles, steps, timeout=5.0)
            means = sorted(v.mean() for _, v in results)
            assert means == pytest.approx([0.0, 1.0, 2.0, 3.0])
        finally:
            ex.shutdown()

    def test_shutdown_stops_workers(self, executor):
        executor.shutdown()
        remaining = [n for n in executor._worker_manager.list_workers() if n.startswith("chain_pool_")]
        assert remaining == []


class TestSubmitCollect:
    def test_submit_single_result(self, executor, frame):
        step = make_step("n1", BrightenOperation(7))
        handle = executor.submit(step.operation, frame.copy(), None)
        assert handle.result(timeout=5).mean() == pytest.approx(7.0)

    def test_collect_exception(self, executor, frame):
        step = make_step("n1", FailingOperation())
        handles = executor.submit_bundle([step], frame, None)
        results = executor.collect_results(handles, [step], timeout=5)
        _, value = results[0]
        assert isinstance(value, Exception)

    def test_collect_timeout(self, executor, frame):
        class SlowOp:
            def execute(self, data, ctx):
                time.sleep(10)
                return data

            def configure(self, p):
                pass

        step = make_step("slow", SlowOp())
        handles = executor.submit_bundle([step], frame, None)
        results = executor.collect_results(handles, [step], timeout=0.05)
        _, value = results[0]
        assert isinstance(value, TimeoutError)


class TestResize:
    def test_resize_recreates_pool(self, executor, frame):
        executor.resize(1)
        assert executor.max_workers == 1
        pool_workers = [n for n in executor._worker_manager.list_workers() if n.startswith("chain_pool_")]
        assert len(pool_workers) == 1
        # Пул после resize по-прежнему исполняет
        step = make_step("n1", BrightenOperation(3))
        handles = executor.submit_bundle([step], frame, None)
        results = executor.collect_results(handles, [step], timeout=5)
        _, value = results[0]
        assert value.mean() == pytest.approx(3.0)
