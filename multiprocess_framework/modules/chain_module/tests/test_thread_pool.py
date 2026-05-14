"""Тесты ChainThreadPool."""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.chain_module.thread_pool.pool import ChainThreadPool

from .conftest import BrightenOperation, FakeNode, PassthroughOperation, RunnableStep


def make_pool_step(node_id: str, operation=None, on_error: str = "skip") -> RunnableStep:
    node = FakeNode(node_id=node_id)
    op = operation if operation is not None else PassthroughOperation()
    return RunnableStep(node=node, operation=op, on_error=on_error)


@pytest.fixture
def pool():
    p = ChainThreadPool(max_workers=2, step_timeout=5.0)
    yield p
    p.shutdown()


class TestChainThreadPoolInit:
    def test_defaults(self):
        pool = ChainThreadPool()
        assert pool.max_workers >= 1
        assert pool.step_timeout > 0
        pool.shutdown()

    def test_custom_params(self):
        pool = ChainThreadPool(max_workers=4, step_timeout=2.0)
        assert pool.max_workers == 4
        assert pool.step_timeout == 2.0
        pool.shutdown()


class TestChainThreadPoolSubmit:
    def test_submit_single_step(self, pool, frame):
        from multiprocess_framework.modules.chain_module.core.context import ChainContext

        ctx = ChainContext()
        step = make_pool_step("n1", BrightenOperation(5))
        futures = pool.submit_bundle([step], frame, ctx)
        assert len(futures) == 1
        result = futures[0].result(timeout=5)
        assert result.mean() == pytest.approx(5.0)

    def test_submit_multiple_steps(self, pool, frame):
        from multiprocess_framework.modules.chain_module.core.context import ChainContext

        ctx = ChainContext()
        steps = [
            make_pool_step("n1", BrightenOperation(10)),
            make_pool_step("n2", BrightenOperation(20)),
        ]
        futures = pool.submit_bundle(steps, frame, ctx)
        assert len(futures) == 2
        r1 = futures[0].result(timeout=5)
        r2 = futures[1].result(timeout=5)
        assert r1.mean() == pytest.approx(10.0)
        assert r2.mean() == pytest.approx(20.0)

    def test_frame_is_copied_per_step(self, pool, frame):
        """Каждый шаг получает копию кадра для thread-safety."""
        from multiprocess_framework.modules.chain_module.core.context import ChainContext

        received = []

        class CaptureOp:
            def execute(self, data, ctx):
                received.append(id(data))
                return data

            def configure(self, p):
                pass

        steps = [make_pool_step(f"n{i}", CaptureOp()) for i in range(3)]
        ctx = ChainContext()
        pool.submit_bundle(steps, frame, ctx)
        import time

        time.sleep(0.1)
        # Все id разные (копии)
        if len(received) >= 2:
            assert len(set(received)) == len(received)


class TestChainThreadPoolCollect:
    def test_collect_all_done(self, pool, frame):
        from multiprocess_framework.modules.chain_module.core.context import ChainContext

        ctx = ChainContext()
        steps = [make_pool_step("n1", BrightenOperation(5))]
        futures = pool.submit_bundle(steps, frame, ctx)
        results = pool.collect_results(futures, steps, timeout=5)
        assert len(results) == 1
        step_out, value = results[0]
        assert not isinstance(value, Exception)
        assert value.mean() == pytest.approx(5.0)

    def test_collect_with_exception(self, pool, frame):
        from multiprocess_framework.modules.chain_module.core.context import ChainContext
        from .conftest import FailingOperation

        ctx = ChainContext()
        step = make_pool_step("n1", FailingOperation())
        futures = pool.submit_bundle([step], frame, ctx)
        results = pool.collect_results(futures, [step], timeout=5)
        _, value = results[0]
        assert isinstance(value, Exception)

    def test_collect_timeout_marks_timeout(self, pool, frame):
        from multiprocess_framework.modules.chain_module.core.context import ChainContext

        class SlowOp:
            def execute(self, data, ctx):
                time.sleep(10)
                return data

            def configure(self, p):
                pass

        ctx = ChainContext()
        step = make_pool_step("n1", SlowOp())
        futures = pool.submit_bundle([step], frame, ctx)
        # Очень маленький timeout → должен вернуть таймаут
        results = pool.collect_results(futures, [step], timeout=0.01)
        assert len(results) == 1
        _, value = results[0]
        assert isinstance(value, Exception)
