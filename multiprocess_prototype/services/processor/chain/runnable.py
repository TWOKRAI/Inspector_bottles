"""Исполняемая цепочка обработки кадра (Phase 5a MVP)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from registers.pipeline.processing_node import ProcessingNode
from services.processor.operations.base import ChainContext, ProcessingOperation

logger = logging.getLogger(__name__)


@dataclass
class RunnableStep:
    """Один шаг исполняемой цепочки: нода + сконфигурированная операция + политика ошибок."""

    node: ProcessingNode
    operation: ProcessingOperation
    on_error: str  # "skip" | "fail_region" | "fail_camera"


@dataclass
class ChainResult:
    """Результат выполнения цепочки обработки."""

    frame: np.ndarray
    detections: list[dict] = field(default_factory=list)
    masks: list[np.ndarray] = field(default_factory=list)
    contours: list[np.ndarray] = field(default_factory=list)
    processing_time: float = 0.0
    context: ChainContext = field(default_factory=ChainContext)
    skipped_nodes: list[str] = field(default_factory=list)
    failed: bool = False
    fail_level: str | None = None  # "region" | "camera" | None


class IRunnableChain(Protocol):
    """Протокол исполняемой цепочки обработки.

    Структурная типизация — ChainRunnable, ParallelChainRunnable, DagRunnable
    реализуют этот протокол автоматически (без наследования).
    """

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult: ...


class ChainRunnable:
    """Исполняемая цепочка обработки кадра.

    Получает список RunnableStep, последовательно применяет операции к кадру.
    Ошибки обрабатываются согласно on_error политике каждого шага.
    """

    def __init__(self, steps: list[RunnableStep]) -> None:
        self._steps = steps

    @property
    def steps(self) -> list[RunnableStep]:
        """Шаги цепочки (read-only доступ)."""
        return list(self._steps)

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult:
        """Исполнить цепочку последовательно.

        Args:
            frame: Входной кадр (numpy array, BGR).
            metadata: Метаданные — camera_id, region_id, seq_id и т.д.

        Returns:
            ChainResult с финальным кадром, детекциями и диагностикой.
        """
        metadata = metadata or {}

        # Инициализация контекста из metadata
        context = ChainContext(
            camera_id=metadata.get("camera_id", ""),
            region_id=metadata.get("region_id", ""),
            seq_id=metadata.get("seq_id", 0),
        )

        result = ChainResult(frame=frame, context=context)
        current_frame = frame
        t_start = time.perf_counter()

        for step in self._steps:
            try:
                # Phase 5c: cross-process шаг — делегируем в worker pool
                if _is_cross_process(step):
                    response = step.execute_remote(
                        frame=current_frame,
                        context=context,
                        input_shm_name=metadata.get("input_shm_name", ""),
                        input_shm_index=metadata.get("input_shm_index", 0),
                    )
                    # Detections из worker response записываем в result
                    if response.detections:
                        result.detections.extend(response.detections)
                    # Worker не возвращает кадр напрямую — оставляем current_frame
                    continue

                output = step.operation.execute(current_frame, context)
            except Exception as exc:
                if step.on_error == "skip":
                    # Логируем предупреждение, продолжаем с тем же кадром
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={step.node.node_id}) упала с ошибкой: {exc}. "
                        f"on_error=skip — пропускаем."
                    )
                    logger.warning(msg)
                    context.warnings.append(msg)
                    result.skipped_nodes.append(step.node.node_id)
                    continue

                elif step.on_error == "fail_region":
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={step.node.node_id}) упала с ошибкой: {exc}. "
                        f"on_error=fail_region — прерываем цепочку."
                    )
                    logger.error(msg)
                    context.errors.append(msg)
                    result.failed = True
                    result.fail_level = "region"
                    break

                else:
                    # on_error == "fail_camera" или неизвестное значение
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={step.node.node_id}) упала с ошибкой: {exc}. "
                        f"on_error={step.on_error} — прерываем цепочку (camera)."
                    )
                    logger.error(msg)
                    context.errors.append(msg)
                    result.failed = True
                    result.fail_level = "camera"
                    break

            # Успешное выполнение — обновляем текущий кадр
            current_frame = output

            # Извлекаем побочные результаты (детекции, маски, контуры)
            # через duck-typing — не привязываемся к конкретному классу
            _collect_side_results(step.operation, result)

        result.frame = current_frame
        result.processing_time = time.perf_counter() - t_start
        return result


def _is_cross_process(step: Any) -> bool:
    """Проверить, является ли шаг cross-process (CrossProcessStep).

    Используем duck-typing (hasattr) вместо isinstance,
    чтобы избежать циклического импорта cross_process_step ↔ runnable.
    """
    return hasattr(step, "execute_remote") and hasattr(step, "dispatcher")


def _collect_side_results(operation: Any, result: ChainResult) -> None:
    """Извлечь побочные результаты из операции (детекции, маски, контуры).

    Используем hasattr вместо isinstance — не привязываемся к конкретному типу.
    """
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


__all__ = ["ChainRunnable", "ChainResult", "IRunnableChain", "RunnableStep"]
