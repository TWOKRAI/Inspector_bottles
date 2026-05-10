"""Строитель исполняемой цепочки из nodes + каталога (Phase 5a MVP, расширен в 5b)."""

from __future__ import annotations

import logging

from registers.pipeline.processing_node import ProcessingNode
from registers.processor.catalog.port_types import are_ports_compatible
from registers.processor.catalog.schemas import ProcessingOperationDef
from services.processor.operations.loader import load_operation_class
from services.processor.worker_pool.dispatcher import WorkerPoolDispatcher

# Topology-утилиты из фреймворка (Phase 2.3)
from multiprocess_framework.modules.chain_module import (
    topological_sort as _topological_sort,
    is_nonlinear_graph as _is_nonlinear_graph,
    detect_parallel_bundles,
)

from .cross_process_step import CrossProcessStep
from .dag_runnable import DagRunnable
from .parallel_runnable import ParallelChainRunnable
from .runnable import ChainRunnable, RunnableStep
from .thread_pool import ChainThreadPool

logger = logging.getLogger(__name__)


class GraphRunnableBuilder:
    """Строитель исполняемой цепочки из nodes + каталога.

    Принимает dict нод и каталог операций, возвращает готовый ChainRunnable.
    В Phase 5a цепочка линейная, но топологическая сортировка (Kahn's algorithm)
    корректно обрабатывает и DAG-случай для Phase 8.
    """

    @staticmethod
    def build(
        nodes: dict[str, ProcessingNode],
        catalog: dict[str, ProcessingOperationDef],
        pool: ChainThreadPool | None = None,
        dispatcher: WorkerPoolDispatcher | None = None,
    ) -> ChainRunnable | ParallelChainRunnable | DagRunnable:
        """Построить цепочку из nodes и каталога.

        Если граф нелинейный (ветвления/merge) — возвращает DagRunnable.
        Если pool передан и max_workers > 1 — анализирует граф на параллельные бандлы.
        При наличии хотя бы одного бандла с 2+ шагами возвращает ParallelChainRunnable.
        В остальных случаях — ChainRunnable (линейная цепочка, обратная совместимость).

        Шаги:
        1. Фильтрация disabled нод (enabled=False)
        2. Топологическая сортировка по inputs (Kahn's algorithm)
        3. Валидация портов — типы, существование, совместимость
        4. Для каждой active ноды: загрузить класс операции, инстанцировать, configure
        5. Собрать список RunnableStep
        6. Определить тип графа: линейный → Chain/Parallel, нелинейный → DagRunnable

        Args:
            nodes: Словарь node_id -> ProcessingNode.
            catalog: Словарь type_key -> ProcessingOperationDef.
            pool: Пул потоков для параллельного исполнения (опционально).
            dispatcher: WorkerPoolDispatcher для cross-process шагов (опционально).
                Если None и нода имеет process_id="worker_pool_*" — fallback
                на локальное исполнение с WARN.

        Returns:
            ChainRunnable, ParallelChainRunnable или DagRunnable.

        Raises:
            KeyError: Если operation_ref ноды отсутствует в каталоге.
            ValueError: Если обнаружен цикл в графе зависимостей
                или несовместимые типы портов.
        """
        # 1. Фильтрация disabled нод
        active_nodes = {nid: node for nid, node in nodes.items() if node.enabled}

        if not active_nodes:
            logger.info("Нет активных нод — возвращаем пустую цепочку.")
            return ChainRunnable(steps=[])

        # 2. Топологическая сортировка (Kahn's algorithm)
        sorted_nodes = _topological_sort(active_nodes)

        # 3. Валидация портов
        _validate_ports(active_nodes, catalog)

        # 4-5. Загрузка, инстанцирование, конфигурация
        steps: list[RunnableStep] = []
        for node in sorted_nodes:
            op_ref = node.operation_ref

            # Проверяем наличие операции в каталоге
            if op_ref not in catalog:
                raise KeyError(
                    f"Операция '{op_ref}' (node_id={node.node_id}) "
                    f"не найдена в каталоге. "
                    f"Доступные операции: {list(catalog.keys())}"
                )

            op_def = catalog[op_ref]

            # Загружаем класс операции по module_path из каталога
            op_class = load_operation_class(op_def.module_path)

            # Инстанцируем и конфигурируем
            operation = op_class()
            operation.configure(node.params)

            step = RunnableStep(
                node=node,
                operation=operation,
                on_error=op_def.on_error,
            )

            # Phase 5c: оборачиваем в CrossProcessStep для worker_pool нод
            if node.process_id and node.process_id.startswith("worker_pool"):
                if dispatcher is not None:
                    step = CrossProcessStep(step, dispatcher)
                    logger.info(
                        "Нода '%s' (operation=%s) → cross-process через dispatcher.",
                        node.node_id,
                        op_ref,
                    )
                else:
                    logger.warning(
                        "Нода '%s' (operation=%s) имеет process_id='%s', "
                        "но dispatcher=None — fallback на локальное исполнение.",
                        node.node_id,
                        op_ref,
                        node.process_id,
                    )

            steps.append(step)

        # 6. Определение типа графа и выбор runnable
        is_dag = _is_nonlinear_graph(active_nodes)

        if is_dag:
            # Нелинейный граф (ветвление/merge) → DagRunnable
            topology = [n.node_id for n in sorted_nodes]
            node_inputs = {nid: list(node.inputs) for nid, node in active_nodes.items()}
            logger.info(
                "Нелинейный граф → DagRunnable: %d шагов из %d нод (%d disabled).",
                len(steps),
                len(nodes),
                len(nodes) - len(active_nodes),
            )
            return DagRunnable(
                steps=steps,
                topology=topology,
                node_inputs=node_inputs,
            )

        # Линейный граф — проверяем parallel bundles
        if pool is not None and pool.max_workers > 1:
            bundles = detect_parallel_bundles(steps, active_nodes)
            # Параллельный бандл — хотя бы один бандл с 2+ шагами
            has_parallel = any(len(b) > 1 for b in bundles)
            if has_parallel:
                logger.info(
                    "Цепочка: %d шагов, %d бандлов, параллельная.",
                    len(steps),
                    len(bundles),
                )
                return ParallelChainRunnable(bundles=bundles, pool=pool)
            else:
                logger.info(
                    "Цепочка: %d шагов, %d бандлов, линейная (нет параллельных бандлов).",
                    len(steps),
                    len(bundles),
                )
                return ChainRunnable(steps=steps)

        # Pool не задан или max_workers=1 — линейная цепочка (обратная совместимость)
        logger.info(
            "Цепочка построена: %d шагов из %d нод (%d disabled).",
            len(steps),
            len(nodes),
            len(nodes) - len(active_nodes),
        )
        return ChainRunnable(steps=steps)



def _validate_ports(
    nodes: dict[str, ProcessingNode],
    catalog: dict[str, ProcessingOperationDef],
) -> None:
    """Валидация типов портов для всех соединений в графе.

    Для каждой связи (NodeInput) проверяет:
    1. output_port существует в выходных портах source-операции
    2. input_port существует во входных портах target-операции
    3. Типы данных портов совместимы (are_ports_compatible)

    Args:
        nodes: Активные ноды.
        catalog: Каталог операций.

    Raises:
        ValueError: Если порт не найден или типы несовместимы.
    """
    for target_id, target_node in nodes.items():
        target_op_ref = target_node.operation_ref
        if target_op_ref not in catalog:
            # KeyError будет на этапе загрузки — тут только порты
            continue

        target_def = catalog[target_op_ref]
        target_input_ports = {p.name: p for p in target_def.input_ports}

        for inp in target_node.inputs:
            # "frame" — виртуальный источник, порт "out" типа "image"
            if inp.source == "frame" or inp.source not in nodes:
                continue

            source_node = nodes[inp.source]
            source_op_ref = source_node.operation_ref
            if source_op_ref not in catalog:
                continue

            source_def = catalog[source_op_ref]
            source_output_ports = {p.name: p for p in source_def.output_ports}

            # Проверяем: output_port существует у source
            if inp.output_port not in source_output_ports:
                available = list(source_output_ports.keys())
                raise ValueError(
                    f"Порт ошибка: нода '{target_id}' ссылается на выходной порт "
                    f"'{inp.output_port}' ноды '{inp.source}' (операция '{source_op_ref}'), "
                    f"но такого порта нет. Доступные выходные порты: {available}"
                )

            # Проверяем: input_port существует у target
            if inp.input_port not in target_input_ports:
                available = list(target_input_ports.keys())
                raise ValueError(
                    f"Порт ошибка: нода '{target_id}' (операция '{target_op_ref}') "
                    f"не имеет входного порта '{inp.input_port}'. "
                    f"Доступные входные порты: {available}"
                )

            # Проверяем совместимость типов
            output_type = source_output_ports[inp.output_port].data_type
            input_type = target_input_ports[inp.input_port].data_type

            if not are_ports_compatible(output_type, input_type):
                raise ValueError(
                    f"Несовместимые типы портов: "
                    f"нода '{inp.source}' порт '{inp.output_port}' "
                    f"(тип '{output_type}') → "
                    f"нода '{target_id}' порт '{inp.input_port}' "
                    f"(тип '{input_type}'). "
                    f"Операции: '{source_op_ref}' → '{target_op_ref}'"
                )


__all__ = ["GraphRunnableBuilder"]
