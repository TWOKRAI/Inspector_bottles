"""Алгоритм автоматического расположения узлов графа (Sugiyama layered layout).

Реализует три фазы Sugiyama:
1. Layer assignment — назначение слоёв (BFS по зависимостям)
2. Crossing minimization — минимизация пересечений (barycenter heuristic)
3. Coordinate assignment — вычисление координат с snap-to-grid
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ._layout_constants import GRID_SIZE

if TYPE_CHECKING:
    from registers.pipeline.processing_node import ProcessingNode


def _snap_to_grid(value: float, grid: int = GRID_SIZE) -> float:
    """Округлить координату до ближайшего значения, кратного grid."""
    return round(value / grid) * grid


def _build_adjacency(
    nodes: dict[str, ProcessingNode],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Построить графы зависимостей: прямой (deps) и обратный (dependants).

    Returns:
        (deps, dependants) — кто зависит от кого и кто использует кого.
    """
    deps: dict[str, set[str]] = defaultdict(set)
    dependants: dict[str, set[str]] = defaultdict(set)

    all_ids = set(nodes.keys())
    for node_id, node in nodes.items():
        for inp in node.inputs:
            # Связь только с реальными нодами графа (не "frame" и т.п.)
            if inp.source in all_ids:
                deps[node_id].add(inp.source)
                dependants[inp.source].add(node_id)

    return deps, dependants


def _assign_layers(
    nodes: dict[str, ProcessingNode],
    deps: dict[str, set[str]],
    dependants: dict[str, set[str]],
) -> tuple[dict[str, int], list[str]]:
    """Phase 1: назначить каждому узлу слой (layer).

    Слой 0 — узлы без зависимостей (источники).
    Слой N — max(layer[dep]) + 1.

    Returns:
        (layer_map, isolated) — словарь node_id→layer и список изолированных нод.
    """
    all_ids = set(nodes.keys())

    # Узлы, имеющие связи (как зависимости, так и зависимые)
    connected = set()
    for nid in all_ids:
        if deps.get(nid) or dependants.get(nid):
            connected.add(nid)

    isolated = sorted(all_ids - connected)

    # Рекурсивное вычисление уровней с мемоизацией
    layer_map: dict[str, int] = {}

    def _get_layer(node_id: str) -> int:
        if node_id in layer_map:
            return layer_map[node_id]
        node_deps = deps.get(node_id, set())
        if not node_deps:
            layer_map[node_id] = 0
        else:
            layer_map[node_id] = max(_get_layer(d) for d in node_deps) + 1
        return layer_map[node_id]

    for nid in connected:
        _get_layer(nid)

    return layer_map, isolated


def _group_by_layer(layer_map: dict[str, int]) -> dict[int, list[str]]:
    """Сгруппировать узлы по слоям. Возвращает {layer_index: [node_ids]}."""
    layers: dict[int, list[str]] = defaultdict(list)
    for node_id, layer_idx in layer_map.items():
        layers[layer_idx].append(node_id)
    # Сортируем узлы внутри каждого слоя для детерминированности
    for layer_idx in layers:
        layers[layer_idx].sort()
    return layers


def _minimize_crossings(
    layers: dict[int, list[str]],
    deps: dict[str, set[str]],
    dependants: dict[str, set[str]],
    iterations: int = 3,
) -> dict[int, list[str]]:
    """Phase 2: минимизация пересечений рёбер (barycenter heuristic).

    Выполняет forward + backward pass для переупорядочивания узлов внутри слоёв.

    Args:
        layers: слои с начальным порядком узлов.
        deps: зависимости (предшественники).
        dependants: зависимые (последователи).
        iterations: количество полных итераций (forward + backward).

    Returns:
        Обновлённый словарь слоёв с оптимизированным порядком.
    """
    if not layers:
        return layers

    sorted_layer_indices = sorted(layers.keys())

    for _ in range(iterations):
        # Forward pass: от первого слоя ко последнему
        for i in range(1, len(sorted_layer_indices)):
            layer_idx = sorted_layer_indices[i]
            prev_layer_idx = sorted_layer_indices[i - 1]
            prev_order = layers[prev_layer_idx]
            # Позиции узлов предыдущего слоя
            pos_map = {nid: pos for pos, nid in enumerate(prev_order)}

            # Вычисляем barycenter для каждого узла текущего слоя
            barycenters: dict[str, float] = {}
            for nid in layers[layer_idx]:
                # Ищем зависимости этого узла в предыдущем слое
                node_deps = deps.get(nid, set())
                positions = [pos_map[d] for d in node_deps if d in pos_map]
                if positions:
                    barycenters[nid] = sum(positions) / len(positions)
                else:
                    # Нет зависимостей в предыдущем слое — оставляем текущую позицию
                    current_pos = layers[layer_idx].index(nid)
                    barycenters[nid] = float(current_pos)

            layers[layer_idx] = sorted(layers[layer_idx], key=lambda nid: barycenters[nid])

        # Backward pass: от последнего слоя к первому
        for i in range(len(sorted_layer_indices) - 2, -1, -1):
            layer_idx = sorted_layer_indices[i]
            next_layer_idx = sorted_layer_indices[i + 1]
            next_order = layers[next_layer_idx]
            pos_map = {nid: pos for pos, nid in enumerate(next_order)}

            barycenters: dict[str, float] = {}
            for nid in layers[layer_idx]:
                # Ищем зависимых от этого узла в следующем слое
                node_deps = dependants.get(nid, set())
                positions = [pos_map[d] for d in node_deps if d in pos_map]
                if positions:
                    barycenters[nid] = sum(positions) / len(positions)
                else:
                    current_pos = layers[layer_idx].index(nid)
                    barycenters[nid] = float(current_pos)

            layers[layer_idx] = sorted(layers[layer_idx], key=lambda nid: barycenters[nid])

    return layers


def _assign_coordinates(
    layers: dict[int, list[str]],
    isolated: list[str],
    node_width: float,
    node_height: float,
    h_spacing: float,
    v_spacing: float,
) -> dict[str, tuple[float, float]]:
    """Phase 3: вычислить координаты (x, y) для каждого узла.

    Для LR-направления: слой → X-столбец, позиция в слое → Y-строка.
    Каждый слой центрируется по вертикали относительно самого высокого слоя.
    Координаты округляются до GRID_SIZE.
    """
    positions: dict[str, tuple[float, float]] = {}

    if not layers and not isolated:
        return positions

    # Максимальное количество узлов в одном слое (для центрирования)
    max_layer_size = max((len(nids) for nids in layers.values()), default=0)

    # Полная высота самого большого слоя
    max_total_height = max_layer_size * (node_height + v_spacing) - v_spacing

    sorted_layer_indices = sorted(layers.keys())

    for layer_idx in sorted_layer_indices:
        node_ids = layers[layer_idx]
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
        iso_y_offset = (max_total_height - iso_height) / 2.0 if max_total_height > 0 else 0.0

        for pos_in_layer, nid in enumerate(isolated):
            y = iso_y_offset + pos_in_layer * (node_height + v_spacing)
            positions[nid] = (_snap_to_grid(iso_x), _snap_to_grid(y))

    # Сдвигаем все позиции так, чтобы минимум был в (0, 0) или положительный
    if positions:
        min_x = min(p[0] for p in positions.values())
        min_y = min(p[1] for p in positions.values())
        # Сдвиг до неотрицательных координат
        shift_x = -min_x if min_x < 0 else 0.0
        shift_y = -min_y if min_y < 0 else 0.0
        if shift_x or shift_y:
            positions = {
                nid: (_snap_to_grid(x + shift_x), _snap_to_grid(y + shift_y))
                for nid, (x, y) in positions.items()
            }

    return positions


def auto_layout(
    nodes: dict[str, ProcessingNode],
    node_width: float = 180,
    node_height: float = 80,
    h_spacing: float = 100,
    v_spacing: float = 60,
    direction: str = "LR",
) -> dict[str, tuple[float, float]]:
    """Вычислить позиции узлов по алгоритму Sugiyama (layered).

    Три фазы:
    1. Layer assignment — назначение слоёв по зависимостям
    2. Crossing minimization — barycenter heuristic
    3. Coordinate assignment — вычисление (x, y) с snap-to-grid

    Args:
        nodes: словарь node_id → ProcessingNode.
        node_width: ширина ноды в пикселях.
        node_height: высота ноды в пикселях.
        h_spacing: горизонтальный отступ между слоями.
        v_spacing: вертикальный отступ между нодами в одном слое.
        direction: направление раскладки ("LR" — left-to-right).

    Returns:
        Словарь {node_id: (x, y)} с вычисленными позициями.
    """
    if not nodes:
        return {}

    # Построение графа зависимостей
    deps, dependants = _build_adjacency(nodes)

    # Phase 1: назначение слоёв
    layer_map, isolated = _assign_layers(nodes, deps, dependants)

    # Группировка по слоям
    layers = _group_by_layer(layer_map)

    # Phase 2: минимизация пересечений
    layers = _minimize_crossings(layers, deps, dependants)

    # Phase 3: координаты
    positions = _assign_coordinates(layers, isolated, node_width, node_height, h_spacing, v_spacing)

    return positions


__all__ = ["auto_layout"]
