"""Тесты ParallelChainRunnable — параллельные бандлы + cross-process ветка.

Главный кейс: cross-process шаг (реализующий IRemoteExecutable) должен
исполняться через ``execute_remote``, а не ``operation.execute``.
До рефакторинга 2026-05 эта ветка отсутствовала в parallel-исполнителе —
регрессия фиксируется тестами в этом модуле.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from multiprocess_framework.modules.chain_module.core.parallel import ParallelChainRunnable
from multiprocess_framework.modules.chain_module.core.result import ChainResult, RunnableStep
from multiprocess_framework.modules.chain_module.thread_pool.pool import ChainThreadPool

from .conftest import (
    BrightenOperation,
    DetectionOperation,
    FailingOperation,
    FakeNode,
    PassthroughOperation,
    make_step,
)


@dataclass
class FakeRemoteResponse:
    """Эрзац WorkerTaskResponse — только нужные поля."""
    detections: list[dict] = field(default_factory=list)


class FakeCrossProcessStep:
    """Шаг с cross-process исполнением — реализует IRemoteExecutable неявно.

    Не имеет ``operation.execute`` (см. ниже): если parallel-исполнитель
    забудет проверить ``_is_cross_process``, он попытается вызвать
    ``operation.execute(frame, ctx)`` и упадёт с AttributeError.
    """

    def __init__(
        self,
        node_id: str,
        operation_ref: str = "remote_op",
        detections: list[dict] | None = None,
        on_error: str = "fail_camera",
    ) -> None:
        self.node = FakeNode(node_id=node_id, operation_ref=operation_ref)
        # Преднамеренно НЕ операция, а sentinel — execute() отсутствует:
        self.operation = object()
        self.on_error = on_error
        self.dispatcher = object()  # любой объект — нужен для _is_cross_process
        self._detections = detections or []
        self.execute_remote_calls: list[dict[str, Any]] = []

    def execute_remote(
        self,
        frame: np.ndarray,
        context: Any,
        input_shm_name: str,
        input_shm_index: int,
    ) -> FakeRemoteResponse:
        self.execute_remote_calls.append(
            {
                "frame_shape": frame.shape,
                "input_shm_name": input_shm_name,
                "input_shm_index": input_shm_index,
            }
        )
        return FakeRemoteResponse(detections=list(self._detections))


@pytest.fixture
def pool():
    p = ChainThreadPool(max_workers=2, step_timeout=2.0)
    yield p
    p.shutdown()


class TestParallelCrossProcess:
    def test_cross_process_in_single_bundle(self, pool, frame):
        """Один cross-process шаг в бандле → execute_remote вызван."""
        remote_step = FakeCrossProcessStep("remote1", detections=[{"box": [0, 0, 5, 5]}])
        runner = ParallelChainRunnable(bundles=[[remote_step]], pool=pool)

        result = runner.execute(
            frame,
            metadata={"input_shm_name": "shm_test", "input_shm_index": 7},
        )

        assert isinstance(result, ChainResult)
        assert len(remote_step.execute_remote_calls) == 1
        assert remote_step.execute_remote_calls[0]["input_shm_name"] == "shm_test"
        assert remote_step.execute_remote_calls[0]["input_shm_index"] == 7
        assert result.detections == [{"box": [0, 0, 5, 5]}]
        assert result.failed is False

    def test_cross_process_mixed_with_local_in_bundle(self, pool, frame):
        """Бандл из cross-process + local: оба исполняются, результаты собраны."""
        remote_step = FakeCrossProcessStep("remote1", detections=[{"box": [1, 2, 3, 4]}])
        local_step = make_step("local1", BrightenOperation(7))

        runner = ParallelChainRunnable(bundles=[[remote_step, local_step]], pool=pool)
        result = runner.execute(frame)

        assert len(remote_step.execute_remote_calls) == 1
        assert result.detections == [{"box": [1, 2, 3, 4]}]
        # Локальный шаг применился — кадр посветлел на 7
        assert result.frame.mean() == pytest.approx(7.0)
        assert result.failed is False

    def test_cross_process_in_separate_bundles(self, pool, frame):
        """Cross-process в одном бандле, local в следующем — оба отрабатывают."""
        remote_step = FakeCrossProcessStep("remote1", detections=[{"x": 1}])
        local_step = make_step("local1", BrightenOperation(3))

        runner = ParallelChainRunnable(
            bundles=[[remote_step], [local_step]],
            pool=pool,
        )
        result = runner.execute(frame)

        assert len(remote_step.execute_remote_calls) == 1
        assert result.detections == [{"x": 1}]
        assert result.frame.mean() == pytest.approx(3.0)

    def test_cross_process_failure_with_skip(self, pool, frame):
        """Cross-process падает с on_error=skip → warning, цепочка продолжается."""
        class FailingRemoteStep(FakeCrossProcessStep):
            def execute_remote(self, frame, context, input_shm_name, input_shm_index):
                raise RuntimeError("remote down")

        remote_step = FailingRemoteStep("remote1", on_error="skip")
        local_step = make_step("local1", BrightenOperation(2))

        runner = ParallelChainRunnable(
            bundles=[[remote_step], [local_step]],
            pool=pool,
        )
        result = runner.execute(frame)

        assert result.failed is False
        assert "remote1" in result.skipped_nodes
        assert any("remote down" in w for w in result.context.warnings)
        # Локальный шаг применился
        assert result.frame.mean() == pytest.approx(2.0)

    def test_cross_process_failure_with_fail_region(self, pool, frame):
        """Cross-process падает с on_error=fail_region → break, локальные не исполняются."""
        class FailingRemoteStep(FakeCrossProcessStep):
            def execute_remote(self, frame, context, input_shm_name, input_shm_index):
                raise RuntimeError("remote down")

        remote_step = FailingRemoteStep("remote1", on_error="fail_region")
        local_step = make_step("local1", BrightenOperation(99))

        runner = ParallelChainRunnable(
            bundles=[[remote_step], [local_step]],
            pool=pool,
        )
        result = runner.execute(frame)

        assert result.failed is True
        assert result.fail_level == "region"
        # Локальный шаг НЕ применялся
        assert result.frame.mean() == pytest.approx(0.0)


class TestParallelLocalOnly:
    """Регрессионные кейсы для существующего поведения (без cross-process)."""

    def test_single_step_bundle(self, pool, frame):
        runner = ParallelChainRunnable(bundles=[[make_step("n1", BrightenOperation(5))]], pool=pool)
        result = runner.execute(frame)
        assert result.frame.mean() == pytest.approx(5.0)
        assert result.failed is False

    def test_parallel_bundle_first_successful_frame_wins(self, pool, frame):
        """В параллельном бандле first_successful_frame определяет current_frame."""
        steps = [
            make_step("n1", BrightenOperation(10)),
            make_step("n2", BrightenOperation(20)),
        ]
        runner = ParallelChainRunnable(bundles=[steps], pool=pool)
        result = runner.execute(frame)
        # Один из двух — порядок определяется submission order
        assert result.frame.mean() in (pytest.approx(10.0), pytest.approx(20.0))

    def test_failing_step_with_skip_continues(self, pool, frame):
        steps_b1 = [make_step("n1", FailingOperation(), on_error="skip")]
        steps_b2 = [make_step("n2", BrightenOperation(5))]
        runner = ParallelChainRunnable(bundles=[steps_b1, steps_b2], pool=pool)
        result = runner.execute(frame)
        assert result.failed is False
        assert "n1" in result.skipped_nodes
        assert result.frame.mean() == pytest.approx(5.0)

    def test_detections_collected_in_parallel_bundle(self, pool, frame):
        det1 = [{"box": [0, 0, 5, 5], "score": 0.8}]
        det2 = [{"box": [10, 10, 15, 15], "score": 0.7}]
        steps = [
            make_step("n1", DetectionOperation(det1)),
            make_step("n2", DetectionOperation(det2)),
        ]
        runner = ParallelChainRunnable(bundles=[steps], pool=pool)
        result = runner.execute(frame)
        assert len(result.detections) == 2

    def test_passthrough_preserves_frame(self, pool, frame):
        runner = ParallelChainRunnable(bundles=[[make_step("n1", PassthroughOperation())]], pool=pool)
        result = runner.execute(frame)
        np.testing.assert_array_equal(result.frame, frame)
