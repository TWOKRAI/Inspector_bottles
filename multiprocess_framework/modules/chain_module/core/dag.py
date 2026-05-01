"""DagRunnable — исполнитель DAG (направленного ацикличного графа) обработки.

Поддерживает ветвления (1→N) и слияния (N→1) через именованные порты.
Каждая нода получает входы из port_data и записывает выходы обратно.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .context import ChainContext
from .result import ChainResult, RunnableStep, _collect_side_results, _is_cross_process

logger = logging.getLogger(__name__)


class DagRunnable:
    """Исполняемый DAG — обрабатывает данные через граф с ветвлениями и merge.

    В отличие от ChainRunnable, передаёт данные через port_data:
    каждая нода получает {port_name: value} и возвращает {port_name: value}.

    Args:
        steps: Список шагов (RunnableStep) — топологически отсортирован.
        topology: Порядок исполнения нод (список node_id).
        node_inputs: Карта входных соединений {node_id: [conn, ...]}
                     (conn реализует INodeConnection: .source, .input_port, .output_port).
    """

    def __init__(
        self,
        steps: list[RunnableStep],
        topology: list[str],
        node_inputs: dict[str, list[Any]],
    ) -> None:
        self._steps = steps
        self._topology = topology
        self._node_inputs = node_inputs
        self._step_by_id: dict[str, RunnableStep] = {
            step.node.node_id: step for step in steps
        }

    @property
    def steps(self) -> list[RunnableStep]:
        return list(self._steps)

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult:
        """Исполнить DAG по топологическому порядку.

        Виртуальный источник "frame" предоставляет входной кадр через порт "out".

        Args:
            frame: Входной кадр (numpy array).
            metadata: Метаданные — camera_id, region_id, seq_id и т.д.

        Returns:
            ChainResult с финальным кадром, детекциями и диагностикой.
        """
        metadata = metadata or {}

        context = ChainContext(
            camera_id=metadata.get("camera_id", ""),
            region_id=metadata.get("region_id", ""),
            seq_id=metadata.get("seq_id", 0),
        )

        result = ChainResult(frame=frame, context=context)
        t_start = time.perf_counter()

        port_data: dict[str, dict[str, Any]] = {"frame": {"out": frame}}
        last_node_id: str | None = None

        for node_id in self._topology:
            if node_id not in self._step_by_id:
                continue

            step = self._step_by_id[node_id]
            last_node_id = node_id

            inputs: dict[str, Any] = {}
            node_inp_list = self._node_inputs.get(node_id, [])
            for inp in node_inp_list:
                source_data = port_data.get(inp.source)
                if source_data is not None and inp.output_port in source_data:
                    inputs[inp.input_port] = source_data[inp.output_port]
                else:
                    inputs[inp.input_port] = None

            if not node_inp_list:
                inputs["in"] = frame

            try:
                if _is_cross_process(step):
                    response = step.execute_remote(
                        frame=inputs.get("in", frame),
                        context=context,
                        input_shm_name=metadata.get("input_shm_name", ""),
                        input_shm_index=metadata.get("input_shm_index", 0),
                    )
                    if response.detections:
                        result.detections.extend(response.detections)
                    port_data[node_id] = {"out": inputs.get("in", frame)}
                    continue

                outputs = _execute_dag_default(step.operation, inputs, context)

            except Exception as exc:
                if step.on_error == "skip":
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={node_id}) упала: {exc}. on_error=skip — пропускаем."
                    )
                    logger.warning(msg)
                    context.warnings.append(msg)
                    result.skipped_nodes.append(node_id)
                    port_data[node_id] = {}
                    continue

                elif step.on_error == "fail_region":
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={node_id}) упала: {exc}. on_error=fail_region."
                    )
                    logger.error(msg)
                    context.errors.append(msg)
                    result.failed = True
                    result.fail_level = "region"
                    break

                else:
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={node_id}) упала: {exc}. "
                        f"on_error={step.on_error} (camera)."
                    )
                    logger.error(msg)
                    context.errors.append(msg)
                    result.failed = True
                    result.fail_level = "camera"
                    break

            port_data[node_id] = outputs
            _collect_side_results(step.operation, result)

        if last_node_id and last_node_id in port_data:
            final_outputs = port_data[last_node_id]
            if "out" in final_outputs and final_outputs["out"] is not None:
                result.frame = final_outputs["out"]
            else:
                for value in final_outputs.values():
                    if isinstance(value, np.ndarray):
                        result.frame = value
                        break

        result.processing_time = time.perf_counter() - t_start
        return result


def _execute_dag_default(
    operation: Any,
    inputs: dict[str, Any],
    context: ChainContext,
) -> dict[str, Any]:
    """Вызов операции с поддержкой DAG-native и legacy-интерфейса.

    Если операция реализует execute_dag(inputs, context) → dict — используем его.
    Иначе вызываем legacy execute(frame, context) → frame, оборачиваем в {"out": frame}.
    """
    if hasattr(operation, "execute_dag"):
        return operation.execute_dag(inputs, context)

    primary_input = inputs.get("in")
    if primary_input is None:
        primary_input = inputs.get("frame")
    if primary_input is None and inputs:
        primary_input = next(iter(inputs.values()))

    output = operation.execute(primary_input, context)
    return {"out": output}


__all__ = ["DagRunnable"]
