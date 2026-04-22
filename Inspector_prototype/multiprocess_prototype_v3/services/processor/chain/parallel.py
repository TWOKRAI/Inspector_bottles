"""Определение параллельных бандлов из topological sort (Phase 5b).

Алгоритм level assignment: каждой ноде назначается уровень на основе
максимальной глубины её зависимостей. Ноды одного уровня без взаимных
зависимостей группируются в бандл для параллельного исполнения.
"""

from __future__ import annotations

from collections import defaultdict

from registers.pipeline.processing_node import ProcessingNode
from services.processor.chain.runnable import RunnableStep


def detect_parallel_bundles(
    steps: list[RunnableStep],
    nodes: dict[str, ProcessingNode],
) -> list[list[RunnableStep]]:
    """Разбить topologically sorted шаги на параллельные бандлы.

    Args:
        steps: Линейно отсортированные шаги (topological order).
        nodes: Словарь всех нод графа по node_id.

    Returns:
        Список бандлов. Каждый бандл — список шагов, исполняемых параллельно.
        Бандлы упорядочены по уровню (0, 1, 2, ...).
    """
    if not steps:
        return []

    # Множество активных нод (только те, что в steps)
    active_ids = {step.node.node_id for step in steps}

    # Зависимости каждой ноды (только от активных нод)
    deps: dict[str, set[str]] = {}
    for step in steps:
        node = step.node
        node_deps: set[str] = set()
        for inp in node.inputs:
            if inp.source in active_ids:
                node_deps.add(inp.source)
        deps[node.node_id] = node_deps

    # Назначение уровней: нода без зависимостей → 0,
    # нода с зависимостями → max(level[dep]) + 1
    level: dict[str, int] = {}

    def _get_level(node_id: str) -> int:
        """Рекурсивно вычислить уровень ноды (с мемоизацией)."""
        if node_id in level:
            return level[node_id]
        node_deps = deps.get(node_id, set())
        if not node_deps:
            level[node_id] = 0
        else:
            level[node_id] = max(_get_level(d) for d in node_deps) + 1
        return level[node_id]

    for step in steps:
        _get_level(step.node.node_id)

    # Группировка шагов по уровням
    levels: dict[int, list[RunnableStep]] = defaultdict(list)
    for step in steps:
        levels[level[step.node.node_id]].append(step)

    # Разделение внутри уровня по явному worker_id:
    # ноды с разным явным worker_id (не None) не объединяются.
    # Ноды с worker_id=None объединяются свободно с любой группой.
    bundles: list[list[RunnableStep]] = []

    for lvl in sorted(levels):
        group = levels[lvl]
        # Разбиваем по явному worker_id
        worker_groups: dict[str | None, list[RunnableStep]] = defaultdict(list)
        free: list[RunnableStep] = []  # worker_id=None — свободные ноды

        for step in group:
            wid = step.node.worker_id
            if wid is None:
                free.append(step)
            else:
                worker_groups[wid].append(step)

        if not worker_groups:
            # Все ноды свободны — один бандл
            bundles.append(free)
        else:
            # Каждый явный worker_id → отдельный бандл
            for wid in sorted(worker_groups):
                bundles.append(worker_groups[wid])
            # Свободные ноды — отдельный бандл (если есть)
            if free:
                bundles.append(free)

    return bundles


__all__ = ["detect_parallel_bundles"]
