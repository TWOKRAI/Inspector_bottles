"""SugiyamaLayout — автоматическая раскладка DAG (Sugiyama / layered layout).

Generic API: принимает nodes + edges, возвращает позиции.
"""
from __future__ import annotations

from collections import defaultdict

from . import dag_utils

# Grid snap по умолчанию
GRID_SIZE = 20

__all__ = [
    "auto_layout",
    "GRID_SIZE",
]


def auto_layout(
    nodes: list[str],
    edges: list[tuple[str, str]],
    *,
    node_width: float = 160,
    node_height: float = 60,
    h_spacing: float = 100,
    v_spacing: float = 60,
) -> dict[str, tuple[float, float]]:
    """Рассчитать позиции узлов по алгоритму Sugiyama.

    Args:
        nodes: список node_id.
        edges: список рёбер (source, target).
        node_width, node_height: размеры узла.
        h_spacing: горизонтальный отступ между колонками.
        v_spacing: вертикальный отступ между рядами.

    Returns:
        dict[node_id, (x, y)] — позиции узлов.
    """
    if not nodes:
        return {}

    node_set = set(nodes)
    valid_edges = [(s, t) for s, t in edges if s in node_set and t in node_set]

    # Phase 1: Layer assignment
    layers, isolated = _assign_layers(node_set, valid_edges)

    # Phase 2: Crossing minimization
    grouped = _group_by_layer(layers)
    grouped = _minimize_crossings(grouped, valid_edges)

    # Phase 3: Coordinate assignment
    positions = _assign_coordinates(
        grouped, isolated, node_width, node_height, h_spacing, v_spacing
    )

    return positions


# ---- Phase 1: Layer Assignment ---- #


def _assign_layers(
    nodes: set[str], edges: list[tuple[str, str]]
) -> tuple[dict[str, int], list[str]]:
    """BFS layer assignment. Layer 0 = root-ноды (нет входящих).

    Рекурсивно: layer(node) = max(layer(dep) for dep in deps) + 1.

    Returns:
        (layer_map, isolated_ids)
    """
    # Построить графы зависимостей
    deps: dict[str, set[str]] = defaultdict(set)
    dependants: dict[str, set[str]] = defaultdict(set)

    for src, tgt in edges:
        deps[tgt].add(src)  # tgt зависит от src
        dependants[src].add(tgt)

    # Определить связные и изолированные ноды
    connected: set[str] = set()
    for nid in nodes:
        if deps.get(nid) or dependants.get(nid):
            connected.add(nid)

    isolated = sorted(nodes - connected)

    # Проверка на циклы — при цикле fallback на плоский layout
    if dag_utils.has_cycle(edges):
        layer_map = {nid: 0 for nid in connected}
        return layer_map, isolated

    # Рекурсивное вычисление уровней с мемоизацией и sentinel
    layer_map: dict[str, int] = {}
    _visiting: set[str] = set()  # sentinel для защиты от неожиданных циклов

    def _get_layer(node_id: str) -> int:
        if node_id in layer_map:
            return layer_map[node_id]
        if node_id in _visiting:
            # Не должно случиться после has_cycle check, но страховка
            layer_map[node_id] = 0
            return 0
        _visiting.add(node_id)
        node_deps = deps.get(node_id, set())
        if not node_deps:
            layer_map[node_id] = 0
        else:
            layer_map[node_id] = max(_get_layer(d) for d in node_deps) + 1
        _visiting.discard(node_id)
        return layer_map[node_id]

    for nid in sorted(connected):
        _get_layer(nid)

    return layer_map, isolated


# ---- Phase 2: Crossing Minimization ---- #


def _minimize_crossings(
    grouped: dict[int, list[str]],
    edges: list[tuple[str, str]],
    iterations: int = 3,
) -> dict[int, list[str]]:
    """Barycenter heuristic: несколько итераций forward + backward.

    Переупорядочивает узлы внутри каждого слоя для минимизации
    пересечений рёбер на основе средней позиции соседей.
    """
    if not grouped:
        return grouped

    # Построить deps/dependants для быстрого доступа
    deps: dict[str, set[str]] = defaultdict(set)
    dependants: dict[str, set[str]] = defaultdict(set)
    for src, tgt in edges:
        deps[tgt].add(src)
        dependants[src].add(tgt)

    sorted_layer_indices = sorted(grouped.keys())

    for _ in range(iterations):
        # Forward pass: от первого слоя к последнему
        for i in range(1, len(sorted_layer_indices)):
            layer_idx = sorted_layer_indices[i]
            prev_layer_idx = sorted_layer_indices[i - 1]
            prev_order = grouped[prev_layer_idx]
            # Позиции узлов предыдущего слоя
            pos_map = {nid: pos for pos, nid in enumerate(prev_order)}

            barycenters: dict[str, float] = {}
            for nid in grouped[layer_idx]:
                # Зависимости этого узла в предыдущем слое
                node_deps = deps.get(nid, set())
                positions = [pos_map[d] for d in node_deps if d in pos_map]
                if positions:
                    barycenters[nid] = sum(positions) / len(positions)
                else:
                    current_pos = grouped[layer_idx].index(nid)
                    barycenters[nid] = float(current_pos)

            grouped[layer_idx] = sorted(
                grouped[layer_idx], key=lambda nid: barycenters[nid]
            )

        # Backward pass: от последнего слоя к первому
        for i in range(len(sorted_layer_indices) - 2, -1, -1):
            layer_idx = sorted_layer_indices[i]
            next_layer_idx = sorted_layer_indices[i + 1]
            next_order = grouped[next_layer_idx]
            pos_map = {nid: pos for pos, nid in enumerate(next_order)}

            barycenters: dict[str, float] = {}
            for nid in grouped[layer_idx]:
                # Зависимые от этого узла в следующем слое
                node_deps = dependants.get(nid, set())
                positions = [pos_map[d] for d in node_deps if d in pos_map]
                if positions:
                    barycenters[nid] = sum(positions) / len(positions)
                else:
                    current_pos = grouped[layer_idx].index(nid)
                    barycenters[nid] = float(current_pos)

            grouped[layer_idx] = sorted(
                grouped[layer_idx], key=lambda nid: barycenters[nid]
            )

    return grouped


# ---- Phase 3: Coordinate Assignment ---- #


def _assign_coordinates(
    grouped: dict[int, list[str]],
    isolated: list[str],
    node_width: float,
    node_height: float,
    h_spacing: float,
    v_spacing: float,
) -> dict[str, tuple[float, float]]:
    """Рассчитать финальные координаты.

    Для LR-направления: слой -> X-столбец, позиция в слое -> Y-строка.
    Каждый слой центрируется по вертикали относительно самого высокого слоя.
    Координаты округляются до GRID_SIZE.
    """
    positions: dict[str, tuple[float, float]] = {}

    if not grouped and not isolated:
        return positions

    # Максимальное количество узлов в одном слое (для центрирования)
    max_layer_size = max((len(nids) for nids in grouped.values()), default=0)

    # Полная высота самого большого слоя
    max_total_height = max_layer_size * (node_height + v_spacing) - v_spacing
    if max_total_height < 0:
        max_total_height = 0

    sorted_layer_indices = sorted(grouped.keys())

    for layer_idx in sorted_layer_indices:
        node_ids = grouped[layer_idx]
        x = layer_idx * (node_width + h_spacing)

        # Высота текущего слоя
        layer_height = len(node_ids) * (node_height + v_spacing) - v_spacing
        # Смещение для центрирования
        y_offset = (max_total_height - layer_height) / 2.0

        for pos_in_layer, nid in enumerate(node_ids):
            y = y_offset + pos_in_layer * (node_height + v_spacing)
            positions[nid] = (_snap_to_grid(x), _snap_to_grid(y))

    # Изолированные узлы — отдельный столбец справа
    if isolated:
        iso_layer = sorted_layer_indices[-1] + 1 if sorted_layer_indices else 0
        iso_x = iso_layer * (node_width + h_spacing)
        iso_height = len(isolated) * (node_height + v_spacing) - v_spacing
        iso_y_offset = (
            (max_total_height - iso_height) / 2.0 if max_total_height > 0 else 0.0
        )

        for pos_in_layer, nid in enumerate(isolated):
            y = iso_y_offset + pos_in_layer * (node_height + v_spacing)
            positions[nid] = (_snap_to_grid(iso_x), _snap_to_grid(y))

    # Сдвигаем все позиции так, чтобы минимум был >= (0, 0)
    if positions:
        min_x = min(p[0] for p in positions.values())
        min_y = min(p[1] for p in positions.values())
        shift_x = -min_x if min_x < 0 else 0.0
        shift_y = -min_y if min_y < 0 else 0.0
        if shift_x or shift_y:
            positions = {
                nid: (_snap_to_grid(x + shift_x), _snap_to_grid(y + shift_y))
                for nid, (x, y) in positions.items()
            }

    return positions


# ---- Helpers ---- #


def _group_by_layer(layer_map: dict[str, int]) -> dict[int, list[str]]:
    """Группировка по слоям."""
    grouped: dict[int, list[str]] = {}
    for node, layer in layer_map.items():
        grouped.setdefault(layer, []).append(node)
    for layer in grouped:
        grouped[layer].sort()
    return grouped


def _snap_to_grid(value: float, grid: int = GRID_SIZE) -> float:
    """Snap к ближайшей точке grid."""
    return round(value / grid) * grid
