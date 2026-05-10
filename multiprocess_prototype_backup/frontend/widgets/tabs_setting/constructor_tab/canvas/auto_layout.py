"""Sugiyama layered layout для процесс-нод конструктора.

Три фазы:
1. Layer assignment — назначение слоёв (BFS по wire-зависимостям)
2. Crossing minimization — barycenter heuristic
3. Coordinate assignment — вычисление координат с snap-to-grid

Адаптировано из pipeline_tab/canvas/auto_layout.py
для межпроцессных wire-зависимостей.
"""

from __future__ import annotations

from collections import defaultdict

# Размеры для конструкторских нод (больше чем pipeline-ноды)
GRID_SIZE = 20
DEFAULT_NODE_WIDTH = 240
DEFAULT_NODE_HEIGHT = 160
DEFAULT_H_SPACING = 120
DEFAULT_V_SPACING = 80


def _snap(value: float, grid: int = GRID_SIZE) -> float:
    return round(value / grid) * grid


def _build_adjacency(
    wires: dict[str, dict],
    process_keys: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Построить графы зависимостей из wire-связей.

    Args:
        wires: wire_key → {"source": "proc.plugin.port", "target": "proc.plugin.port"}
        process_keys: множество ключей процессов.

    Returns:
        (deps, dependants) — кто зависит от кого.
    """
    deps: dict[str, set[str]] = defaultdict(set)
    dependants: dict[str, set[str]] = defaultdict(set)

    for _wk, wire in wires.items():
        src_proc = wire.get("source", "").split(".")[0]
        tgt_proc = wire.get("target", "").split(".")[0]
        if src_proc in process_keys and tgt_proc in process_keys and src_proc != tgt_proc:
            deps[tgt_proc].add(src_proc)
            dependants[src_proc].add(tgt_proc)

    return deps, dependants


def _assign_layers(
    process_keys: set[str],
    deps: dict[str, set[str]],
    dependants: dict[str, set[str]],
) -> tuple[dict[str, int], list[str]]:
    """Назначить слой каждому процессу.

    Слой 0 — процессы без входящих wire (источники данных).
    """
    connected = {
        pk for pk in process_keys if deps.get(pk) or dependants.get(pk)
    }
    isolated = sorted(process_keys - connected)

    layer_map: dict[str, int] = {}

    def _get_layer(pk: str) -> int:
        if pk in layer_map:
            return layer_map[pk]
        pk_deps = deps.get(pk, set())
        if not pk_deps:
            layer_map[pk] = 0
        else:
            layer_map[pk] = max(_get_layer(d) for d in pk_deps) + 1
        return layer_map[pk]

    for pk in connected:
        _get_layer(pk)

    return layer_map, isolated


def _group_by_layer(layer_map: dict[str, int]) -> dict[int, list[str]]:
    layers: dict[int, list[str]] = defaultdict(list)
    for pk, layer_idx in layer_map.items():
        layers[layer_idx].append(pk)
    for layer_idx in layers:
        layers[layer_idx].sort()
    return layers


def _minimize_crossings(
    layers: dict[int, list[str]],
    deps: dict[str, set[str]],
    dependants: dict[str, set[str]],
    iterations: int = 3,
) -> dict[int, list[str]]:
    """Barycenter heuristic для минимизации пересечений."""
    if not layers:
        return layers

    sorted_indices = sorted(layers.keys())

    for _ in range(iterations):
        # Forward pass
        for i in range(1, len(sorted_indices)):
            idx = sorted_indices[i]
            prev_idx = sorted_indices[i - 1]
            pos_map = {pk: pos for pos, pk in enumerate(layers[prev_idx])}

            bary: dict[str, float] = {}
            for pk in layers[idx]:
                positions = [pos_map[d] for d in deps.get(pk, set()) if d in pos_map]
                bary[pk] = (
                    sum(positions) / len(positions) if positions
                    else float(layers[idx].index(pk))
                )
            layers[idx] = sorted(layers[idx], key=lambda pk: bary[pk])

        # Backward pass
        for i in range(len(sorted_indices) - 2, -1, -1):
            idx = sorted_indices[i]
            next_idx = sorted_indices[i + 1]
            pos_map = {pk: pos for pos, pk in enumerate(layers[next_idx])}

            bary: dict[str, float] = {}
            for pk in layers[idx]:
                positions = [pos_map[d] for d in dependants.get(pk, set()) if d in pos_map]
                bary[pk] = (
                    sum(positions) / len(positions) if positions
                    else float(layers[idx].index(pk))
                )
            layers[idx] = sorted(layers[idx], key=lambda pk: bary[pk])

    return layers


def auto_layout(
    process_keys: set[str],
    wires: dict[str, dict],
    node_width: float = DEFAULT_NODE_WIDTH,
    node_height: float = DEFAULT_NODE_HEIGHT,
    h_spacing: float = DEFAULT_H_SPACING,
    v_spacing: float = DEFAULT_V_SPACING,
) -> dict[str, tuple[float, float]]:
    """Вычислить позиции процесс-нод по алгоритму Sugiyama.

    Args:
        process_keys: Множество ключей процессов.
        wires: wire_key → wire dict (source/target).
        node_width: Ширина ноды.
        node_height: Высота ноды.
        h_spacing: Горизонтальный отступ.
        v_spacing: Вертикальный отступ.

    Returns:
        {process_key: (x, y)} — позиции для set_pos().
    """
    if not process_keys:
        return {}

    deps, dependants = _build_adjacency(wires, process_keys)
    layer_map, isolated = _assign_layers(process_keys, deps, dependants)
    layers = _group_by_layer(layer_map)
    layers = _minimize_crossings(layers, deps, dependants)

    positions: dict[str, tuple[float, float]] = {}

    if not layers and not isolated:
        return positions

    max_layer_size = max((len(pks) for pks in layers.values()), default=0)
    max_total_height = max(
        max_layer_size * (node_height + v_spacing) - v_spacing, 0.0,
    )

    sorted_indices = sorted(layers.keys())

    for layer_idx in sorted_indices:
        pks = layers[layer_idx]
        x = layer_idx * (node_width + h_spacing)
        layer_height = len(pks) * (node_height + v_spacing) - v_spacing
        y_offset = (max_total_height - layer_height) / 2.0

        for pos_in_layer, pk in enumerate(pks):
            y = y_offset + pos_in_layer * (node_height + v_spacing)
            positions[pk] = (_snap(x), _snap(y))

    # Изолированные — отдельный столбец справа
    if isolated:
        iso_layer = sorted_indices[-1] + 1 if sorted_indices else 0
        iso_x = iso_layer * (node_width + h_spacing)
        iso_height = len(isolated) * (node_height + v_spacing) - v_spacing
        iso_y_offset = (max_total_height - iso_height) / 2.0 if max_total_height > 0 else 0.0

        for pos_in_layer, pk in enumerate(isolated):
            y = iso_y_offset + pos_in_layer * (node_height + v_spacing)
            positions[pk] = (_snap(iso_x), _snap(y))

    # Сдвиг до неотрицательных координат
    if positions:
        min_x = min(p[0] for p in positions.values())
        min_y = min(p[1] for p in positions.values())
        if min_x < 0 or min_y < 0:
            sx = -min_x if min_x < 0 else 0.0
            sy = -min_y if min_y < 0 else 0.0
            positions = {
                pk: (_snap(x + sx), _snap(y + sy))
                for pk, (x, y) in positions.items()
            }

    return positions


__all__ = ["auto_layout"]
