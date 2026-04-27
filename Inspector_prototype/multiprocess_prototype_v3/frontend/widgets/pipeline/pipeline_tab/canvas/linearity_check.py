"""Утилита проверки линейности графа обработки."""

from __future__ import annotations

from collections import defaultdict


def is_linear(nodes: dict) -> bool:
    """Проверить, что граф линеен (каждая нода имеет ≤1 input и ≤1 зависимую ноду).

    Args:
        nodes: dict node_id → ProcessingNode

    Returns:
        True если граф линеен.
    """
    # Множество активных нод (исключаем внешние источники вроде "frame")
    active_ids = set(nodes.keys())
    # Подсчёт out_degree: сколько нод зависит от данной ноды
    out_degree: dict[str, int] = defaultdict(int)

    for node in nodes.values():
        # Реальные входы — только те, источник которых есть среди активных нод
        real_inputs = [inp for inp in node.inputs if inp.source in active_ids]
        # Нелинейность: нода имеет более одного входа (merge)
        if len(real_inputs) > 1:
            return False
        # Подсчёт зависимых нод для каждого источника
        for inp in node.inputs:
            if inp.source in active_ids:
                out_degree[inp.source] += 1

    # Нелинейность: источник имеет более одной зависимой ноды (ветвление)
    return all(d <= 1 for d in out_degree.values())


def get_linearity_warning(nodes: dict) -> str | None:
    """Вернуть предупреждение если граф нелинеен, иначе None.

    Args:
        nodes: dict node_id → ProcessingNode

    Returns:
        Строка предупреждения или None если граф линеен.
    """
    if is_linear(nodes):
        return None

    active_ids = set(nodes.keys())
    out_degree: dict[str, int] = defaultdict(int)
    merges = 0

    for node in nodes.values():
        real_inputs = [inp for inp in node.inputs if inp.source in active_ids]
        # Merge: нода с несколькими входами
        if len(real_inputs) > 1:
            merges += 1
        for inp in node.inputs:
            if inp.source in active_ids:
                out_degree[inp.source] += 1

    # Ветвления: нода с несколькими зависимыми
    branches = sum(1 for d in out_degree.values() if d > 1)

    return (
        f"Граф нелинеен: {branches} ветвлений, {merges} merge. "
        "Часть связей скрыта в табличном виде."
    )
