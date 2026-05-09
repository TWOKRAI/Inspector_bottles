"""dag_utils — универсальные DAG-алгоритмы (pure Python, 0 зависимостей).

Кандидат в multiprocess_framework/modules/frontend_module/graph/ после Phase 14.
"""
from __future__ import annotations


def has_cycle(
    edges: list[tuple[str, str]], new_edge: tuple[str, str] | None = None
) -> bool:
    """Проверить наличие цикла в графе (DFS).

    Args:
        edges: существующие рёбра [(source, target), ...].
        new_edge: опциональное новое ребро для проверки
                  "а будет ли цикл если добавить?".

    Returns:
        True если цикл найден.
    """
    all_edges = list(edges)
    if new_edge:
        all_edges.append(new_edge)

    # Построить adjacency list
    adj: dict[str, list[str]] = {}
    nodes: set[str] = set()
    for src, tgt in all_edges:
        adj.setdefault(src, []).append(tgt)
        nodes.add(src)
        nodes.add(tgt)

    # DFS с тремя цветами: WHITE=0, GRAY=1, BLACK=2
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in nodes}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            if color[neighbor] == GRAY:
                return True  # back edge — цикл
            if color[neighbor] == WHITE and dfs(neighbor):
                return True
        color[node] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in nodes)


def topological_sort(nodes: set[str], edges: list[tuple[str, str]]) -> list[str]:
    """Топологическая сортировка (Kahn's algorithm).

    Returns:
        Отсортированный список node_id. Пустой если граф имеет цикл.
    """
    in_degree: dict[str, int] = {n: 0 for n in nodes}
    adj: dict[str, list[str]] = {n: [] for n in nodes}

    for src, tgt in edges:
        if src in nodes and tgt in nodes:
            adj[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue = sorted([n for n in nodes if in_degree[n] == 0])
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbor in sorted(adj.get(node, [])):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result if len(result) == len(nodes) else []


def validate_port_compatibility(src_dtype: str, tgt_dtype: str) -> bool:
    """Проверить совместимость портов по dtype.

    Поддерживает:
    - "any" совместим с любым dtype
    - Wildcard: "image/*" принимает "image/bgr", "image/gray"
    - Точное совпадение dtype
    - Backward compat: старые вызовы с direction-значениями ("output"/"input")
      обрабатываются по старой логике: output→input=True, остальное=False

    Args:
        src_dtype: dtype источника ("image/bgr", "any", "image/*")
                   или legacy direction ("output")
        tgt_dtype: dtype назначения или legacy direction ("input")

    Returns:
        True если типы совместимы.
    """
    # Backward compat: если оба аргумента — direction-значения ("input"/"output"),
    # используем старую логику (только output→input = True)
    _DIRECTIONS = {"input", "output"}
    if src_dtype in _DIRECTIONS and tgt_dtype in _DIRECTIONS:
        return src_dtype == "output" and tgt_dtype == "input"

    # "any" совместим с чем угодно
    if src_dtype == "any" or tgt_dtype == "any":
        return True

    # Точное совпадение
    if src_dtype == tgt_dtype:
        return True

    # Wildcard: "image/*" принимает "image/bgr", "image/gray" и т.д.
    if tgt_dtype.endswith("/*"):
        prefix = tgt_dtype[:-2]  # "image"
        if src_dtype.startswith(prefix + "/") or src_dtype == prefix:
            return True

    # Wildcard на источнике: "image/*" совместим с "image/bgr" на входе
    if src_dtype.endswith("/*"):
        prefix = src_dtype[:-2]
        if tgt_dtype.startswith(prefix + "/") or tgt_dtype == prefix:
            return True

    return False


def find_connected_edges(
    edges: list[tuple[str, str]], node_id: str
) -> list[tuple[str, str]]:
    """Найти все рёбра, связанные с узлом (для каскадного удаления)."""
    return [(s, t) for s, t in edges if s == node_id or t == node_id]
