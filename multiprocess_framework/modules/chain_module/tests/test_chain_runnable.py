"""Тесты ChainRunnable — последовательный исполнитель цепочки."""
from __future__ import annotations

import numpy as np
import pytest

from multiprocess_framework.modules.chain_module.core.chain import ChainRunnable
from multiprocess_framework.modules.chain_module.core.result import ChainResult

from .conftest import (
    BrightenOperation,
    DetectionOperation,
    FailingOperation,
    FakeNode,
    PassthroughOperation,
    RunnableStep,
    make_step,
)


class TestChainRunnableBasic:
    def test_empty_chain_returns_unchanged_frame(self, frame):
        chain = ChainRunnable(steps=[])
        result = chain.execute(frame)
        assert isinstance(result, ChainResult)
        np.testing.assert_array_equal(result.frame, frame)

    def test_single_passthrough_step(self, frame, metadata):
        chain = ChainRunnable(steps=[make_step("n1")])
        result = chain.execute(frame, metadata)
        np.testing.assert_array_equal(result.frame, frame)
        assert result.context.camera_id == "cam0"
        assert result.context.region_id == "reg0"
        assert result.context.seq_id == 42

    def test_sequential_transform_accumulates(self, frame):
        steps = [
            make_step("n1", BrightenOperation(10)),
            make_step("n2", BrightenOperation(10)),
        ]
        chain = ChainRunnable(steps)
        result = chain.execute(frame)
        assert result.frame.mean() == pytest.approx(20.0)

    def test_steps_property_returns_copy(self, frame):
        steps = [make_step("n1"), make_step("n2")]
        chain = ChainRunnable(steps)
        returned = chain.steps
        assert len(returned) == 2
        # Изменение возвращённого списка не влияет на chain
        returned.clear()
        assert len(chain.steps) == 2

    def test_metadata_defaults_when_missing(self, frame):
        chain = ChainRunnable(steps=[make_step("n1")])
        result = chain.execute(frame)
        assert result.context.camera_id == ""
        assert result.context.region_id == ""
        assert result.context.seq_id == 0

    def test_processing_time_positive(self, frame):
        chain = ChainRunnable(steps=[make_step("n1")])
        result = chain.execute(frame)
        assert result.processing_time >= 0.0


class TestChainRunnableOnError:
    def test_on_error_skip_continues_chain(self, frame):
        steps = [
            make_step("n1", FailingOperation(), on_error="skip"),
            make_step("n2", BrightenOperation(5)),
        ]
        chain = ChainRunnable(steps)
        result = chain.execute(frame)
        # n1 пропущен, n2 применился → среднее значение 5
        assert result.frame.mean() == pytest.approx(5.0)
        assert result.failed is False
        assert "n1" in result.skipped_nodes
        assert len(result.context.warnings) == 1

    def test_on_error_skip_appends_warning(self, frame):
        chain = ChainRunnable([make_step("n1", FailingOperation(), on_error="skip")])
        result = chain.execute(frame)
        assert any("намеренная ошибка" in w for w in result.context.warnings)

    def test_on_error_fail_region_stops_chain(self, frame):
        steps = [
            make_step("n1", FailingOperation(), on_error="fail_region"),
            make_step("n2", BrightenOperation(5)),
        ]
        chain = ChainRunnable(steps)
        result = chain.execute(frame)
        assert result.failed is True
        assert result.fail_level == "region"
        # n2 не должен был применяться
        assert result.frame.mean() == pytest.approx(0.0)
        assert len(result.context.errors) == 1

    def test_on_error_fail_camera_stops_chain(self, frame):
        steps = [
            make_step("n1", FailingOperation(), on_error="fail_camera"),
            make_step("n2", BrightenOperation(99)),
        ]
        chain = ChainRunnable(steps)
        result = chain.execute(frame)
        assert result.failed is True
        assert result.fail_level == "camera"
        assert result.frame.mean() == pytest.approx(0.0)


class TestChainRunnableSideResults:
    def test_detections_collected(self, frame):
        expected_detections = [{"box": [0, 0, 5, 5], "score": 0.8}]
        op = DetectionOperation(expected_detections)
        chain = ChainRunnable([make_step("n1", op)])
        result = chain.execute(frame)
        assert result.detections == expected_detections

    def test_detections_from_multiple_steps(self, frame):
        op1 = DetectionOperation([{"box": [0, 0, 5, 5], "score": 0.8}])
        op2 = DetectionOperation([{"box": [10, 10, 15, 15], "score": 0.7}])
        chain = ChainRunnable([make_step("n1", op1), make_step("n2", op2)])
        result = chain.execute(frame)
        assert len(result.detections) == 2

    def test_no_detections_by_default(self, frame):
        chain = ChainRunnable([make_step("n1")])
        result = chain.execute(frame)
        assert result.detections == []
        assert result.masks == []
        assert result.contours == []
