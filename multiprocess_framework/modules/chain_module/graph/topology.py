"""Топологическая сортировка и анализ графа нод обработки.

Все функции принимают узлы через duck-typing (IStepNode Protocol):
.node_id: str, .inputs: list (элементы с .source: str).
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


def topological_sort(nodes: dict[str, Any]) -> list[Any]:
    """Топологическая сортировка нод по алгоритму Кана (Kahn's algorithm).

    Учитывает зависимости через node.inputs[].source.
    Нода без inputs (или с source='frame') идёт первой.

    Args:
        nodes: Словарь node_id → нода (реализует IStepNode).

    Returns:
        Список нод в порядке выполнения.

    Raises:
        ValueError: Если обнаружен цикл в графе.
    """
    active_ids = set(nodes.keys())

    in_degree: dict[str, int] = {nid: 0 for nid in active_ids}
    dependents: dict[str, list[str]] = defaultdict(list)

    for nid, node in nodes.items():
        for inp in node.inputs:
            if inp.source in active_ids:
                in_degree[nid] += 1
                dependents[inp.source].append(nid)

    queue: deque[str] = deque(
        nid for nid in active_ids if in_degree[nid] == 0
    )

    sorted_result: list[Any] = []

    while queue:
        nid = queue.popleft()
        sorted_result.append(nodes[nid])
        for dep_id in dependents[nid]:
            in_degree[dep_id] -= 1
            if in_degree[dep_id] == 0:
                queue.append(dep_id)

    if len(sorted_result) != len(active_ids):
        processed = {n.node_id for n in sorted_result}
        remaining = active_ids - processed
        raise ValueError(
            f"Обнаружен цикл в графе обработки. Ноды в цикле: {remaining}"
        )

    return sorted_result


def is_nonlinear_graph(nodes: dict[str, Any]) -> bool:
    """Определить, является ли граф нелинейным (ветвление или merge).

    Граф линеен, если каждая нода имеет не более 1 входа из активных нод
    и является источником не более чем для 1 другой ноды.

    Returns:
        True если граф нелинейный (требуется DagRunnable).
    """
    active_ids = set(nodes.keys())

    for node in nodes.values():
        active_inputs = [inp for inp in node.inputs if inp.source in active_ids]
        if len(active_inputs) > 1:
            return True

    dependents_count: dict[str, int] = {nid: 0 for nid in active_ids}
    for node in nodes.values():
        for inp in node.inputs:
            if inp.source in active_ids:
                dependents_count[inp.source] += 1

    return any(count > 1 for count in dependents_count.values())


__all__ = ["topological_sort", "is_nonlinear_graph"]
