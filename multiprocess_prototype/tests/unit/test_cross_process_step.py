"""Unit-тесты для CrossProcessStep (Phase 5c, cross_process_step.py)."""

from __future__ import annotations

import sys
from pathlib import Path

_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

import numpy as np
import pytest

from registers.pipeline.processing_node import NodeInput, ProcessingNode
from services.processor.chain.cross_process_step import CrossProcessStep
from services.processor.chain.runnable import RunnableStep
from services.processor.operations.base import ChainContext
from services.processor.worker_pool.protocol import WorkerTaskResponse


# ---------------------------------------------------------------------------
# Вспомогательные моки
# ---------------------------------------------------------------------------


class MockOp:
    """Минимальная операция для заполнения RunnableStep."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        return frame

    def configure(self, params: dict) -> None:
        pass


class MockDispatcher:
    """Mock диспетчера с заданным ответом."""

    def __init__(self, response: WorkerTaskResponse) -> None:
        self._response = response
        self.call_count = 0
        self.last_kwargs: dict = {}

    def dispatch(self, **kwargs) -> WorkerTaskResponse:
        self.call_count += 1
        self.last_kwargs = kwargs
        return self._response


def make_runnable_step(operation_ref: str = "test_op") -> RunnableStep:
    """Создать RunnableStep с минимальной нодой."""
    node = ProcessingNode(
        node_id="n1",
        operation_ref=operation_ref,
        inputs=[NodeInput(source="frame")],
    )
    return RunnableStep(node=node, operation=MockOp(), on_error="skip")


def make_cross_process_step(
    response: WorkerTaskResponse,
    operation_ref: str = "test_op",
) -> tuple[CrossProcessStep, MockDispatcher]:
    """Создать CrossProcessStep с mock dispatcher."""
    step = make_runnable_step(operation_ref)
    dispatcher = MockDispatcher(response=response)
    cross_step = CrossProcessStep(step=step, dispatcher=dispatcher)
    return cross_step, dispatcher


def make_success_response(task_id: str = "t1") -> WorkerTaskResponse:
    return WorkerTaskResponse(task_id=task_id, success=True, processing_time=0.01)


def make_error_response(task_id: str = "t1", error: str = "worker failed") -> WorkerTaskResponse:
    return WorkerTaskResponse.error_response(task_id=task_id, error=error)


# ---------------------------------------------------------------------------
# Тесты проксирования атрибутов
# ---------------------------------------------------------------------------


class TestAttributeProxy:
    def test_node_proxied_from_inner_step(self):
        """CrossProcessStep.node проксируется к внутреннему step.node."""
        cross_step, _ = make_cross_process_step(make_success_response())
        inner_step = make_runnable_step()

        # Создаём новый cross_step и проверяем node
        node = ProcessingNode(node_id="proxy-n1", operation_ref="proxy_op")
        inner = RunnableStep(node=node, operation=MockOp(), on_error="skip")
        cs = CrossProcessStep(step=inner, dispatcher=MockDispatcher(make_success_response()))

        assert cs.node is inner.node
        assert cs.node.node_id == "proxy-n1"
        assert cs.node.operation_ref == "proxy_op"

    def test_operation_proxied_from_inner_step(self):
        """CrossProcessStep.operation проксируется к внутреннему step.operation."""
        op = MockOp()
        node = ProcessingNode(node_id="n2", operation_ref="op_ref")
        inner = RunnableStep(node=node, operation=op, on_error="fail_region")
        cs = CrossProcessStep(step=inner, dispatcher=MockDispatcher(make_success_response()))

        assert cs.operation is op

    def test_on_error_proxied_from_inner_step(self):
        """CrossProcessStep.on_error проксируется к внутреннему step.on_error."""
        node = ProcessingNode(node_id="n3", operation_ref="op_ref")
        inner = RunnableStep(node=node, operation=MockOp(), on_error="fail_camera")
        cs = CrossProcessStep(step=inner, dispatcher=MockDispatcher(make_success_response()))

        assert cs.on_error == "fail_camera"


# ---------------------------------------------------------------------------
# Тесты duck-typing
# ---------------------------------------------------------------------------


class TestDuckTyping:
    def test_has_execute_remote_attribute(self):
        """CrossProcessStep имеет атрибут execute_remote."""
        cs, _ = make_cross_process_step(make_success_response())
        assert hasattr(cs, "execute_remote")

    def test_has_dispatcher_attribute(self):
        """CrossProcessStep имеет атрибут dispatcher."""
        cs, _ = make_cross_process_step(make_success_response())
        assert hasattr(cs, "dispatcher")

    def test_execute_remote_is_callable(self):
        """execute_remote является callable."""
        cs, _ = make_cross_process_step(make_success_response())
        assert callable(cs.execute_remote)


# ---------------------------------------------------------------------------
# Тесты execute_remote — успешный случай
# ---------------------------------------------------------------------------


class TestExecuteRemoteSuccess:
    def test_execute_remote_returns_response_on_success(self):
        """execute_remote() → успешный response возвращается без исключений."""
        response = make_success_response(task_id="t-ok")
        cs, dispatcher = make_cross_process_step(response)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        context = ChainContext(camera_id="cam0", region_id="r0", seq_id=1)

        result = cs.execute_remote(
            frame=frame,
            context=context,
            input_shm_name="shm_in",
            input_shm_index=0,
        )

        assert result.success is True
        assert result.task_id == "t-ok"

    def test_execute_remote_calls_dispatcher_dispatch(self):
        """execute_remote() вызывает dispatcher.dispatch() ровно один раз."""
        response = make_success_response()
        cs, dispatcher = make_cross_process_step(response)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        context = ChainContext(camera_id="cam0", region_id="r0", seq_id=5)

        cs.execute_remote(
            frame=frame,
            context=context,
            input_shm_name="shm_in",
            input_shm_index=2,
        )

        assert dispatcher.call_count == 1

    def test_execute_remote_passes_correct_kwargs_to_dispatcher(self):
        """execute_remote() передаёт в dispatcher правильные camera_id, region_id, seq_id."""
        response = make_success_response()
        cs, dispatcher = make_cross_process_step(response, operation_ref="color_detection")

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        context = ChainContext(camera_id="cam2", region_id="r7", seq_id=42)

        cs.execute_remote(
            frame=frame,
            context=context,
            input_shm_name="shm_color",
            input_shm_index=3,
        )

        kwargs = dispatcher.last_kwargs
        assert kwargs["camera_id"] == "cam2"
        assert kwargs["region_id"] == "r7"
        assert kwargs["seq_id"] == 42
        assert kwargs["input_shm_name"] == "shm_color"
        assert kwargs["input_shm_index"] == 3
        assert kwargs["operation_ref"] == "color_detection"

    def test_execute_remote_passes_frame_shape_to_dispatcher(self):
        """execute_remote() передаёт frame.shape в dispatcher."""
        response = make_success_response()
        cs, dispatcher = make_cross_process_step(response)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        context = ChainContext(camera_id="cam0", region_id="r0", seq_id=0)

        cs.execute_remote(
            frame=frame,
            context=context,
            input_shm_name="shm",
            input_shm_index=0,
        )

        assert dispatcher.last_kwargs["frame_shape"] == (480, 640, 3)


# ---------------------------------------------------------------------------
# Тесты execute_remote — случай ошибки
# ---------------------------------------------------------------------------


class TestExecuteRemoteError:
    def test_execute_remote_raises_runtime_error_on_failure(self):
        """execute_remote() → response.success=False → RuntimeError."""
        response = make_error_response(error="worker crashed")
        cs, _ = make_cross_process_step(response)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        context = ChainContext(camera_id="cam0", region_id="r0", seq_id=1)

        with pytest.raises(RuntimeError):
            cs.execute_remote(
                frame=frame,
                context=context,
                input_shm_name="shm",
                input_shm_index=0,
            )

    def test_execute_remote_error_message_contains_operation_ref(self):
        """RuntimeError содержит operation_ref из ноды."""
        response = make_error_response(error="timeout")
        cs, _ = make_cross_process_step(response, operation_ref="blob_detection")

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        context = ChainContext(camera_id="cam0", region_id="r0", seq_id=1)

        with pytest.raises(RuntimeError, match="blob_detection"):
            cs.execute_remote(
                frame=frame,
                context=context,
                input_shm_name="shm",
                input_shm_index=0,
            )

    def test_execute_remote_error_message_contains_error_text(self):
        """RuntimeError содержит текст ошибки из response."""
        response = make_error_response(error="operation failed: OOM")
        cs, _ = make_cross_process_step(response)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        context = ChainContext(camera_id="cam0", region_id="r0", seq_id=1)

        with pytest.raises(RuntimeError, match="operation failed: OOM"):
            cs.execute_remote(
                frame=frame,
                context=context,
                input_shm_name="shm",
                input_shm_index=0,
            )
