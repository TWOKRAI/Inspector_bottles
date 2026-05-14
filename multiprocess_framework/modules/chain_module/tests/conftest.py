"""Общие фикстуры для тестов chain_module."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from multiprocess_framework.modules.chain_module.core.result import RunnableStep


class FakeNode:
    """Минимальная реализация IStepNode для тестов."""

    def __init__(self, node_id: str, operation_ref: str = "op", inputs=None, worker_id=None):
        self.node_id = node_id
        self.operation_ref = operation_ref
        self.inputs = inputs or []
        self.worker_id = worker_id


class FakeConnection:
    """Минимальная реализация INodeConnection для тестов."""

    def __init__(self, source: str, input_port: str = "in", output_port: str = "out"):
        self.source = source
        self.input_port = input_port
        self.output_port = output_port


class PassthroughOperation:
    """Операция-заглушка: возвращает кадр без изменений."""

    def execute(self, data: Any, context: Any) -> Any:
        return data

    def configure(self, params: dict) -> None:
        pass


class BrightenOperation:
    """Операция: добавляет offset к кадру."""

    def __init__(self, offset: int = 10):
        self.offset = offset

    def execute(self, data: np.ndarray, context: Any) -> np.ndarray:
        return np.clip(data.astype(np.int32) + self.offset, 0, 255).astype(np.uint8)

    def configure(self, params: dict) -> None:
        self.offset = params.get("offset", self.offset)


class FailingOperation:
    """Операция, которая всегда падает с RuntimeError."""

    def execute(self, data: Any, context: Any) -> Any:
        raise RuntimeError("намеренная ошибка")

    def configure(self, params: dict) -> None:
        pass


class DetectionOperation:
    """Операция с побочными результатами (детекции)."""

    def __init__(self, detections: list[dict] | None = None):
        self.last_detections = detections or [{"box": [0, 0, 10, 10], "score": 0.9}]

    def execute(self, data: np.ndarray, context: Any) -> np.ndarray:
        return data

    def configure(self, params: dict) -> None:
        pass


def make_step(
    node_id: str,
    operation=None,
    on_error: str = "skip",
    inputs=None,
    operation_ref: str = "op",
) -> RunnableStep:
    node = FakeNode(node_id=node_id, operation_ref=operation_ref, inputs=inputs or [])
    op = operation if operation is not None else PassthroughOperation()
    return RunnableStep(node=node, operation=op, on_error=on_error)


@pytest.fixture
def frame() -> np.ndarray:
    """100x100x3 кадр с нулями."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.fixture
def gray_frame() -> np.ndarray:
    return np.zeros((100, 100), dtype=np.uint8)


@pytest.fixture
def metadata() -> dict:
    return {"camera_id": "cam0", "region_id": "reg0", "seq_id": 42}
