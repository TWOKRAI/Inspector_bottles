"""Тесты DagRunnable — исполнитель DAG с ветвлениями."""

from __future__ import annotations

import numpy as np
import pytest

from multiprocess_framework.modules.chain_module.core.dag import DagRunnable
from multiprocess_framework.modules.chain_module.core.result import ChainResult

from .conftest import (
    BrightenOperation,
    DetectionOperation,
    FailingOperation,
    FakeConnection,
    FakeNode,
    PassthroughOperation,
    RunnableStep,
)


def make_dag_step(node_id: str, operation=None, on_error: str = "skip", inputs=None):
    node = FakeNode(node_id=node_id, inputs=inputs or [])
    op = operation if operation is not None else PassthroughOperation()
    return RunnableStep(node=node, operation=op, on_error=on_error)


class TestDagRunnableBasic:
    def test_single_node_passthrough(self, frame, metadata):
        step = make_dag_step("n1")
        dag = DagRunnable(
            steps=[step],
            topology=["n1"],
            node_inputs={"n1": []},
        )
        result = dag.execute(frame, metadata)
        assert isinstance(result, ChainResult)
        assert result.context.camera_id == "cam0"
        assert result.context.seq_id == 42
        assert result.failed is False

    def test_linear_chain_applies_in_order(self, frame):
        n1 = make_dag_step("n1", BrightenOperation(10), inputs=[])
        n2 = make_dag_step("n2", BrightenOperation(10), inputs=[FakeConnection("n1")])
        dag = DagRunnable(
            steps=[n1, n2],
            topology=["n1", "n2"],
            node_inputs={"n1": [], "n2": [FakeConnection("n1")]},
        )
        result = dag.execute(frame)
        assert result.frame.mean() == pytest.approx(20.0)

    def test_empty_topology(self, frame):
        dag = DagRunnable(steps=[], topology=[], node_inputs={})
        result = dag.execute(frame)
        np.testing.assert_array_equal(result.frame, frame)
        assert result.failed is False

    def test_steps_property_returns_copy(self, frame):
        step = make_dag_step("n1")
        dag = DagRunnable(steps=[step], topology=["n1"], node_inputs={})
        returned = dag.steps
        assert len(returned) == 1
        returned.clear()
        assert len(dag.steps) == 1

    def test_processing_time_set(self, frame):
        dag = DagRunnable(steps=[make_dag_step("n1")], topology=["n1"], node_inputs={})
        result = dag.execute(frame)
        assert result.processing_time >= 0.0


class TestDagRunnableOnError:
    def test_on_error_skip_continues(self, frame):
        n1 = make_dag_step("n1", FailingOperation(), on_error="skip")
        n2 = make_dag_step("n2", BrightenOperation(5))
        dag = DagRunnable(
            steps=[n1, n2],
            topology=["n1", "n2"],
            node_inputs={"n1": [], "n2": []},
        )
        result = dag.execute(frame)
        assert result.failed is False
        assert "n1" in result.skipped_nodes

    def test_on_error_fail_region(self, frame):
        n1 = make_dag_step("n1", FailingOperation(), on_error="fail_region")
        n2 = make_dag_step("n2", BrightenOperation(5))
        dag = DagRunnable(
            steps=[n1, n2],
            topology=["n1", "n2"],
            node_inputs={"n1": [], "n2": []},
        )
        result = dag.execute(frame)
        assert result.failed is True
        assert result.fail_level == "region"

    def test_on_error_fail_camera(self, frame):
        n1 = make_dag_step("n1", FailingOperation(), on_error="fail_camera")
        dag = DagRunnable(
            steps=[n1],
            topology=["n1"],
            node_inputs={"n1": []},
        )
        result = dag.execute(frame)
        assert result.failed is True
        assert result.fail_level == "camera"


class TestDagRunnablePortWiring:
    def test_node_without_inputs_gets_original_frame(self, frame):
        class FrameCapture:
            received = None

            def execute(self, data, ctx):
                FrameCapture.received = data
                return data

            def configure(self, p):
                pass

        op = FrameCapture()
        step = make_dag_step("n1", op, inputs=[])
        dag = DagRunnable(steps=[step], topology=["n1"], node_inputs={"n1": []})
        dag.execute(frame)
        np.testing.assert_array_equal(FrameCapture.received, frame)

    def test_detections_collected(self, frame):
        detections = [{"box": [0, 0, 10, 10], "score": 0.95}]
        op = DetectionOperation(detections)
        step = make_dag_step("n1", op)
        dag = DagRunnable(steps=[step], topology=["n1"], node_inputs={"n1": []})
        result = dag.execute(frame)
        assert result.detections == detections

    def test_node_not_in_step_by_id_is_skipped(self, frame):
        step = make_dag_step("n1")
        # topology содержит "ghost" — нод нет в steps
        dag = DagRunnable(
            steps=[step],
            topology=["ghost", "n1"],
            node_inputs={"n1": []},
        )
        result = dag.execute(frame)
        assert result.failed is False
