"""Эталонная (исходная, 2026-06-15 → 2026-09-04) реализация trace_skeleton.

Хранится в тестах как оракул для новой реализации на плоских индексах:
обе обязаны покрыть каждое ребро скелета ровно один раз и дать одинаковую
суммарную длину. Порядок перебора узлов здесь — порядок set(), поэтому
разбиение на штрихи у развилок может отличаться от растрового.
"""

from __future__ import annotations

import math

import numpy as np

_NB8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def _straightness(prev: tuple[int, int], cur: tuple[int, int], nxt: tuple[int, int]) -> float:
    v1x, v1y = cur[0] - prev[0], cur[1] - prev[1]
    v2x, v2y = nxt[0] - cur[0], nxt[1] - cur[1]
    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 == 0 or n2 == 0:
        return math.pi
    cosang = (v1x * v2x + v1y * v2y) / (n1 * n2)
    return math.acos(max(-1.0, min(1.0, cosang)))


def trace_skeleton_reference(skel: np.ndarray) -> list[np.ndarray]:
    ys, xs = np.nonzero(skel)
    pixels = set(zip(ys.tolist(), xs.tolist()))
    if not pixels:
        return []

    def neigh(p: tuple[int, int]) -> list[tuple[int, int]]:
        y, x = p
        return [(y + dy, x + dx) for dy, dx in _NB8 if (y + dy, x + dx) in pixels]

    degree = {p: len(neigh(p)) for p in pixels}
    used_edges: set = set()
    polylines: list[list[tuple[int, int]]] = []

    def walk(start: tuple[int, int], first: tuple[int, int]) -> list[tuple[int, int]]:
        path = [start, first]
        used_edges.add(frozenset((start, first)))
        prev, cur = start, first
        while True:
            cands = [n for n in neigh(cur) if n != prev and frozenset((cur, n)) not in used_edges]
            if not cands:
                break
            nxt = cands[0] if len(cands) == 1 else min(cands, key=lambda n: _straightness(prev, cur, n))
            used_edges.add(frozenset((cur, nxt)))
            path.append(nxt)
            prev, cur = cur, nxt
            if degree[cur] == 1:
                break
        return path

    for node in [p for p in pixels if degree[p] == 1]:
        for nb in neigh(node):
            if frozenset((node, nb)) not in used_edges:
                path = walk(node, nb)
                if len(path) >= 2:
                    polylines.append(path)

    for node in [p for p in pixels if degree[p] >= 3]:
        for nb in neigh(node):
            if frozenset((node, nb)) not in used_edges:
                path = walk(node, nb)
                if len(path) >= 2:
                    polylines.append(path)

    for p in pixels:
        if degree[p] == 2 and all(frozenset((p, n)) not in used_edges for n in neigh(p)):
            nbs = neigh(p)
            if nbs:
                path = walk(p, nbs[0])
                if len(path) >= 2:
                    polylines.append(path)

    return [np.array([(x, y) for (y, x) in path], dtype=np.float64) for path in polylines]
