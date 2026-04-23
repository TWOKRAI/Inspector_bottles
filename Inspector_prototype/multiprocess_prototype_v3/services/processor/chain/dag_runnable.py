"""Исполняемый DAG (направленный ацикличный граф) обработки кадра (Phase 8).

DagRunnable — расширение линейной ChainRunnable для графов с ветвлениями (1→N)
и слияниями (N→1). Каждая нода получает именованные входы из port_data
и записывает именованные выходы обратно.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
from registers.pipeline.processing_node import NodeInput
from services.processor.operations.base import ChainContext, execute_dag_default

from .runnable import ChainResult, RunnableStep, _collect_side_results, _is_cross_process

logger = logging.getLogger(__name__)


class DagRunnable:
    """Исполняемый DAG — обрабатывает кадр через граф с ветвлениями и merge.

    В отличие от ChainRunnable, передаёт данные через port_data:
    каждая нода получает словарь {port_name: value} и возвращает
    словарь {port_name: value}.

    Args:
        steps: Список шагов (RunnableStep) — уже отсортирован топологически.
        topology: Порядок исполнения нод (список node_id).
        node_inputs: Карта входных соединений {node_id: [NodeInput, ...]}.
    """

    def __init__(
        self,
        steps: list[RunnableStep],
        topology: list[str],
        node_inputs: dict[str, list[NodeInput]],
    ) -> None:
        self._steps = steps
        self._topology = topology
        self._node_inputs = node_inputs

        # Индекс: node_id → RunnableStep для быстрого доступа
        self._step_by_id: dict[str, RunnableStep] = {step.node.node_id: step for step in steps}

    @property
    def steps(self) -> list[RunnableStep]:
        """Шаги DAG (read-only доступ)."""
        return list(self._steps)

    def execute(
        self,
        frame: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> ChainResult:
        """Исполнить DAG по топологическому порядку.

        Виртуальный источник "frame" предоставляет входной кадр
        через порт "out".

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
        t_start = time.perf_counter()

        # port_data: {node_id: {port_name: value}}
        # Виртуальный источник "frame" — предоставляет кадр
        port_data: dict[str, dict[str, Any]] = {
            "frame": {"out": frame},
        }

        # Последняя нода в топологии — её выход станет result.frame
        last_node_id: str | None = None

        for node_id in self._topology:
            if node_id not in self._step_by_id:
                # Нода не в steps (disabled / не найдена) — пропускаем
                continue

            step = self._step_by_id[node_id]
            last_node_id = node_id

            # Собираем входные данные из port_data
            inputs: dict[str, Any] = {}
            node_inp_list = self._node_inputs.get(node_id, [])
            for inp in node_inp_list:
                source_data = port_data.get(inp.source)
                if source_data is not None and inp.output_port in source_data:
                    inputs[inp.input_port] = source_data[inp.output_port]
                else:
                    # Источник ещё не готов или порт отсутствует — None
                    inputs[inp.input_port] = None

            # Если нет явных inputs и нода первая — подаём кадр как "in"
            if not node_inp_list:
                inputs["in"] = frame

            try:
                # Cross-process шаги пока обрабатываем через legacy-интерфейс
                if _is_cross_process(step):
                    response = step.execute_remote(
                        frame=inputs.get("in", frame),
                        context=context,
                        input_shm_name=metadata.get("input_shm_name", ""),
                        input_shm_index=metadata.get("input_shm_index", 0),
                    )
                    if response.detections:
                        result.detections.extend(response.detections)
                    # Cross-process нода — записываем текущий кадр как выход
                    port_data[node_id] = {"out": inputs.get("in", frame)}
                    continue

                # Вызов DAG-обёртки (поддерживает и legacy, и dag-native операции)
                outputs = execute_dag_default(step.operation, inputs, context)

            except Exception as exc:
                if step.on_error == "skip":
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={node_id}) упала с ошибкой: {exc}. "
                        f"on_error=skip — пропускаем."
                    )
                    logger.warning(msg)
                    context.warnings.append(msg)
                    result.skipped_nodes.append(node_id)
                    # Пропущенная нода — передаём None в port_data
                    port_data[node_id] = {}
                    continue

                elif step.on_error == "fail_region":
                    msg = (
                        f"Операция '{step.node.operation_ref}' "
                        f"(node={node_id}) упала с ошибкой: {exc}. "
                        f"on_error=fail_region — прерываем DAG."
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
                        f"(node={node_id}) упала с ошибкой: {exc}. "
                        f"on_error={step.on_error} — прерываем DAG (camera)."
                    )
                    logger.error(msg)
                    context.errors.append(msg)
                    result.failed = True
                    result.fail_level = "camera"
                    break

            # Записываем выходы в port_data
            port_data[node_id] = outputs

            # Собираем побочные результаты (детекции, маски, контуры)
            _collect_side_results(step.operation, result)

        # Финальный кадр — из выхода последней ноды
        if last_node_id and last_node_id in port_data:
            final_outputs = port_data[last_node_id]
            # Берём "out" если есть, иначе первый image-подобный выход
            if "out" in final_outputs and final_outputs["out"] is not None:
                result.frame = final_outputs["out"]
            else:
                # Берём первый не-None выход
                for value in final_outputs.values():
                    if isinstance(value, np.ndarray):
                        result.frame = value
                        break

        result.processing_time = time.perf_counter() - t_start
        return result


__all__ = ["DagRunnable"]
