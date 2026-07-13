"""ChainResult и RunnableStep — основные типы данных цепочки обработки."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..interfaces import IExecutionStep, IStepNode
from .context import ChainContext


@dataclass
class ChainResult:
    """Результат выполнения цепочки обработки."""

    # Финальный payload цепочки (duck-typed): np.ndarray для CV-цепочки ИЛИ
    # list[dict] items для processing-pipeline. Имя ``frame`` сохранено для
    # обратной совместимости существующих CV-потребителей.
    frame: Any
    detections: list[dict] = field(default_factory=list)
    masks: list[np.ndarray] = field(default_factory=list)
    contours: list[np.ndarray] = field(default_factory=list)
    processing_time: float = 0.0
    context: ChainContext = field(default_factory=ChainContext)
    skipped_nodes: list[str] = field(default_factory=list)
    failed: bool = False
    fail_level: str | None = None  # "region" | "camera" | None


@dataclass
class RunnableStep:
    """Один шаг исполняемой цепочки: дескриптор ноды + операция + политика ошибок."""

    node: IStepNode  # .node_id, .operation_ref, .inputs (опц. .worker_id)
    operation: IExecutionStep  # .execute(frame, context), .configure(params)
    on_error: str  # "skip" | "fail_region" | "fail_camera"


def _is_cross_process(step: Any) -> bool:
    """Проверить, является ли шаг cross-process (CrossProcessStep).

    Duck-typing через hasattr — избегаем циклического импорта.
    """
    return hasattr(step, "execute_remote") and hasattr(step, "dispatcher")


def _collect_side_results(operation: Any, result: ChainResult) -> None:
    """Извлечь побочные результаты из операции (детекции, маски, контуры)."""
    if hasattr(operation, "last_detections"):
        detections = operation.last_detections
        if detections:
            result.detections.extend(detections)

    if hasattr(operation, "last_mask"):
        mask = operation.last_mask
        if mask is not None:
            result.masks.append(mask)

    if hasattr(operation, "last_contours"):
        contours = operation.last_contours
        if contours:
            result.contours.extend(contours)


__all__ = ["ChainResult", "RunnableStep", "_is_cross_process", "_collect_side_results"]
