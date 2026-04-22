"""Строитель исполняемой цепочки из nodes + каталога (Phase 5a MVP, расширен в 5b)."""

from __future__ import annotations

import logging
from collections import defaultdict, deque

from registers.pipeline.processing_node import ProcessingNode
from registers.processor.catalog.schemas import ProcessingOperationDef
from services.processor.operations.loader import load_operation_class
from services.processor.worker_pool.dispatcher import WorkerPoolDispatcher

from .cross_process_step import CrossProcessStep
from .parallel import detect_parallel_bundles
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
    ) -> ChainRunnable | ParallelChainRunnable:
        """Построить цепочку из nodes и каталога.

        Если pool передан и max_workers > 1 — анализирует граф на параллельные бандлы.
        При наличии хотя бы одного бандла с 2+ шагами возвращает ParallelChainRunnable.
        В остальных случаях — ChainRunnable (линейная цепочка, обратная совместимость).

        Шаги:
        1. Фильтрация disabled нод (enabled=False)
        2. Топологическая сортировка по inputs (Kahn's algorithm)
        3. Для каждой active ноды: загрузить класс операции, инстанцировать, configure
        4. Собрать список RunnableStep
        5. Если pool задан — определить тип runnable (parallel / linear)

        Args:
            nodes: Словарь node_id -> ProcessingNode.
            catalog: Словарь type_key -> ProcessingOperationDef.
            pool: Пул потоков для параллельного исполнения (опционально).
            dispatcher: WorkerPoolDispatcher для cross-process шагов (опционально).
                Если None и нода имеет process_id="worker_pool_*" — fallback
                на локальное исполнение с WARN.

        Returns:
            ChainRunnable или ParallelChainRunnable.

        Raises:
            KeyError: Если operation_ref ноды отсутствует в каталоге.
            ValueError: Если обнаружен цикл в графе зависимостей.
        """
        # 1. Фильтрация disabled нод
        active_nodes = {
            nid: node for nid, node in nodes.items() if node.enabled
        }

        if not active_nodes:
            logger.info("Нет активных нод — возвращаем пустую цепочку.")
            return ChainRunnable(steps=[])

        # 2. Топологическая сортировка (Kahn's algorithm)
        sorted_nodes = _topological_sort(active_nodes)

        # 3-4. Загрузка, инстанцирование, конфигурация
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

        # 5. Выбор типа runnable: parallel или linear
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


def _topological_sort(
    nodes: dict[str, ProcessingNode],
) -> list[ProcessingNode]:
    """Топологическая сортировка нод по Kahn's algorithm.

    Учитывает зависимости через inputs[].source.
    Нода без inputs (или с source='frame') идёт первой.

    Args:
        nodes: Активные ноды (уже отфильтрованные).

    Returns:
        Список нод в порядке выполнения.

    Raises:
        ValueError: Если обнаружен цикл в графе.
    """
    # Множество id активных нод — для фильтрации ссылок на disabled/внешние
    active_ids = set(nodes.keys())

    # Строим граф: in_degree и adjacency list
    in_degree: dict[str, int] = {nid: 0 for nid in active_ids}
    # dependents[source_id] = список нод, которые зависят от source_id
    dependents: dict[str, list[str]] = defaultdict(list)

    for nid, node in nodes.items():
        for inp in node.inputs:
            # "frame" — внешний источник (входной кадр), не считается зависимостью
            if inp.source in active_ids:
                in_degree[nid] += 1
                dependents[inp.source].append(nid)

    # Очередь: ноды без входящих зависимостей
    queue: deque[str] = deque()
    for nid in active_ids:
        if in_degree[nid] == 0:
            queue.append(nid)

    sorted_result: list[ProcessingNode] = []

    while queue:
        nid = queue.popleft()
        sorted_result.append(nodes[nid])

        for dep_id in dependents[nid]:
            in_degree[dep_id] -= 1
            if in_degree[dep_id] == 0:
                queue.append(dep_id)

    # Проверка на цикл
    if len(sorted_result) != len(active_ids):
        processed = {n.node_id for n in sorted_result}
        remaining = active_ids - processed
        raise ValueError(
            f"Обнаружен цикл в графе обработки. "
            f"Ноды в цикле: {remaining}"
        )

    return sorted_result


__all__ = ["GraphRunnableBuilder"]
