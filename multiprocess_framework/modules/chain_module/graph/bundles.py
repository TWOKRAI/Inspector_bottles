"""Разбиение топологически отсортированных шагов на параллельные бандлы.

Алгоритм level assignment: каждой ноде назначается уровень на основе
максимальной глубины её зависимостей. Ноды одного уровня группируются
в бандл для параллельного исполнения.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def detect_parallel_bundles(
    steps: list[Any],  # список RunnableStep (node.node_id, node.inputs, node.worker_id)
    nodes: dict[str, Any],  # node_id → нода (реализует IStepNodeWithWorker)
) -> list[list[Any]]:
    """Разбить топологически отсортированные шаги на параллельные бандлы.

    Args:
        steps: Линейно отсортированные шаги (topological order).
        nodes: Словарь всех нод графа по node_id.

    Returns:
        Список бандлов. Каждый бандл — список шагов для параллельного исполнения.
        Бандлы упорядочены по уровню (0, 1, 2, ...).
    """
    if not steps:
        return []

    active_ids = {step.node.node_id for step in steps}

    deps: dict[str, set[str]] = {}
    for step in steps:
        node = step.node
        node_deps: set[str] = set()
        for inp in node.inputs:
            if inp.source in active_ids:
                node_deps.add(inp.source)
        deps[node.node_id] = node_deps

    level: dict[str, int] = {}

    def _get_level(node_id: str) -> int:
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

    levels: dict[int, list[Any]] = defaultdict(list)
    for step in steps:
        levels[level[step.node.node_id]].append(step)

    bundles: list[list[Any]] = []

    for lvl in sorted(levels):
        group = levels[lvl]
        worker_groups: dict[str | None, list[Any]] = defaultdict(list)
        free: list[Any] = []

        for step in group:
            # worker_id — опциональный атрибут (IStepNodeWithWorker)
            wid = getattr(step.node, "worker_id", None)
            if wid is None:
                free.append(step)
            else:
                worker_groups[wid].append(step)

        if not worker_groups:
            bundles.append(free)
        else:
            for wid in sorted(worker_groups):
                bundles.append(worker_groups[wid])
            if free:
                bundles.append(free)

    return bundles


__all__ = ["detect_parallel_bundles"]
