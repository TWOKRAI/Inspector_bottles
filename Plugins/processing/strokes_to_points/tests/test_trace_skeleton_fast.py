"""trace_skeleton на плоских индексах против эталона на set/frozenset.

Контракт, который держат оба: каждое ребро скелета (пара 8-соседей) входит
ровно в одну полилинию ровно один раз; соседние точки полилинии 8-смежны;
суммарная длина всех полилиний одинакова (следствие покрытия «ровно один раз»).
Разбиение на штрихи у развилок может отличаться — это НЕ проверяется, и это
сознательно: порядок перебора узлов у эталона — порядок set().
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from Plugins.processing.strokes_to_points import geometry
from Plugins.processing.strokes_to_points.tests._reference_trace import trace_skeleton_reference

_NB8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def _skeleton_edges(skel: np.ndarray) -> set[frozenset]:
    ys, xs = np.nonzero(skel)
    pix = set(zip(ys.tolist(), xs.tolist()))
    edges: set[frozenset] = set()
    for y, x in pix:
        for dy, dx in _NB8:
            q = (y + dy, x + dx)
            if q in pix:
                edges.add(frozenset(((y, x), q)))
    return edges


def _edges_of_polylines(polys: list[np.ndarray]) -> list[frozenset]:
    out: list[frozenset] = []
    for p in polys:
        pts = [(int(y), int(x)) for x, y in p.tolist()]
        for a, b in zip(pts, pts[1:]):
            assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1, f"точки не 8-смежны: {a} → {b}"
            out.append(frozenset((a, b)))
    return out


def _total_len(polys: list[np.ndarray]) -> float:
    return float(sum(np.linalg.norm(np.diff(p, axis=0), axis=1).sum() for p in polys if len(p) > 1))


def _random_skeleton(seed: int, w: int = 160, h: int = 120) -> np.ndarray:
    """Случайные линии, окружности и буква → маска → скелет (как в плагине)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w), dtype=np.uint8)
    for _ in range(int(rng.integers(3, 9))):
        p1 = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        p2 = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        cv2.line(img, p1, p2, 255, int(rng.integers(1, 5)))
    for _ in range(int(rng.integers(0, 4))):
        c = (int(rng.integers(10, w - 10)), int(rng.integers(10, h - 10)))
        cv2.circle(img, c, int(rng.integers(5, 30)), 255, int(rng.integers(1, 4)))
    cv2.putText(
        img, "Ab8", (int(rng.integers(0, w // 2)), int(rng.integers(30, h))), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2
    )
    return geometry.skeletonize_mask(img)


def test_nb8_reverse_table_is_consistent() -> None:
    for i, (dy, dx) in enumerate(geometry._NB8):
        assert geometry._NB8[geometry._REV[i]] == (-dy, -dx)


def test_turn_table_matches_straightness() -> None:
    for a, (ay, ax) in enumerate(geometry._NB8):
        for b, (by, bx) in enumerate(geometry._NB8):
            expected = geometry._straightness((0, 0), (ay, ax), (ay + by, ax + bx))
            assert math.isclose(geometry._TURN[a][b], expected, abs_tol=1e-12)


_IMPLS = [pytest.param(False, id="py")]
if geometry._HAS_NUMBA:
    _IMPLS.append(pytest.param(True, id="numba"))


def test_numba_path_is_the_default_when_installed() -> None:
    if not geometry._HAS_NUMBA:
        pytest.skip("numba не установлена — работает запасной Python-путь")
    skel = np.zeros((6, 12), dtype=np.uint8)
    skel[2, 1:10] = 255
    auto = geometry.trace_skeleton(skel)
    nb = geometry.trace_skeleton(skel, use_numba=True)
    assert [p.tolist() for p in auto] == [p.tolist() for p in nb]


@pytest.mark.parametrize("seed", list(range(25)))
def test_numba_and_python_paths_give_identical_polylines(seed: int) -> None:
    # Оба пути перебирают узлы в растровом порядке с одним правилом развилок,
    # поэтому обязаны совпасть побайтово, а не только по покрытию рёбер.
    if not geometry._HAS_NUMBA:
        pytest.skip("numba не установлена")
    skel = _random_skeleton(seed)
    py = geometry.trace_skeleton(skel, use_numba=False)
    nb = geometry.trace_skeleton(skel, use_numba=True)
    assert len(py) == len(nb)
    for a, b in zip(py, nb):
        assert np.array_equal(a, b)


@pytest.mark.parametrize("use_numba", _IMPLS)
@pytest.mark.parametrize("seed", list(range(25)))
def test_each_edge_covered_exactly_once_and_equal_to_reference(seed: int, use_numba: bool) -> None:
    skel = _random_skeleton(seed)
    expected = _skeleton_edges(skel)
    if not expected:
        pytest.skip("пустой скелет для этого seed")

    fast = geometry.trace_skeleton(skel, use_numba=use_numba)
    ref = trace_skeleton_reference(skel)

    fast_edges = _edges_of_polylines(fast)
    ref_edges = _edges_of_polylines(ref)
    # ровно один раз: как множество совпадает со скелетом, как список — без дублей
    assert set(fast_edges) == expected
    assert len(fast_edges) == len(expected), "ребро пройдено дважды"
    assert set(ref_edges) == expected
    assert len(ref_edges) == len(expected)
    # одинаковое покрытие ⇒ одинаковая суммарная длина
    assert math.isclose(_total_len(fast), _total_len(ref), rel_tol=1e-12)


def test_coordinates_are_xy_without_padding_offset() -> None:
    skel = np.zeros((10, 20), dtype=np.uint8)
    skel[3, 2:9] = 255
    (poly,) = geometry.trace_skeleton(skel)
    assert poly.dtype == np.float64
    assert set(map(tuple, poly.tolist())) == {(float(x), 3.0) for x in range(2, 9)}


def test_closed_loop_is_one_polyline() -> None:
    # Ромб из 8 пикселей: у каждого ровно два 8-соседа (у прямоугольного контура
    # углы имеют диагональных соседей и степень 3 — это НЕ чистая петля).
    skel = np.zeros((7, 7), dtype=np.uint8)
    for y, x in ((1, 3), (2, 2), (3, 1), (4, 2), (5, 3), (4, 4), (3, 5), (2, 4)):
        skel[y, x] = 255
    polys = geometry.trace_skeleton(skel)
    assert len(polys) == 1
    assert len(polys[0]) == 8 + 1  # замкнута: последняя точка = стартовая
    assert np.array_equal(polys[0][0], polys[0][-1])


def test_loop_returning_to_start_does_not_walk_an_edge_twice() -> None:
    # Ромб с «хвостом» из конца степени 1: обход от хвоста входит в петлю,
    # обходит её и возвращается в узел стыка; второе направление узла стыка
    # к этому моменту уже занято и не должно обходиться повторно.
    skel = np.zeros((9, 9), dtype=np.uint8)
    for y, x in ((1, 3), (2, 2), (3, 1), (4, 2), (5, 3), (4, 4), (3, 5), (2, 4)):
        skel[y, x] = 255
    skel[6, 3] = 255
    skel[7, 3] = 255  # хвост вниз от (5,3)
    expected = _skeleton_edges(skel)
    edges = _edges_of_polylines(geometry.trace_skeleton(skel))
    assert set(edges) == expected
    assert len(edges) == len(expected)


def test_figure_eight_does_not_walk_an_edge_twice() -> None:
    # Два ромба с общей вершиной (5,3) степени 4, концов нет. Единственный обход
    # из фазы «развилки» проходит ОБЕ петли и возвращается в вершину, заняв все
    # четыре её направления. Список «непройденных направлений», вычисленный до
    # обхода, здесь устаревает — инъекция I3 (стейл-список) красна именно тут,
    # а тест «петля с хвостом» её не ловит: там у стыка после обхода нет
    # свободных направлений.
    skel = np.zeros((11, 7), dtype=np.uint8)
    for y, x in ((1, 3), (2, 2), (3, 1), (4, 2), (5, 3), (4, 4), (3, 5), (2, 4)):
        skel[y, x] = 255
    for y, x in ((6, 2), (7, 1), (8, 2), (9, 3), (8, 4), (7, 5), (6, 4)):
        skel[y, x] = 255
    expected = _skeleton_edges(skel)
    assert len(expected) == 16
    edges = _edges_of_polylines(geometry.trace_skeleton(skel))
    assert set(edges) == expected
    assert len(edges) == len(expected), "ребро пройдено дважды"


def test_walk_goes_straight_through_a_cross() -> None:
    # Крест: горизонталь и вертикаль. Обход от левого конца в центре видит три
    # кандидата (вверх, вниз, вправо) и обязан выбрать прямое продолжение —
    # вся горизонталь становится одной полилинией от левого конца до правого.
    skel = np.zeros((11, 11), dtype=np.uint8)
    skel[5, 1:10] = 255
    skel[1:10, 5] = 255
    polys = geometry.trace_skeleton(skel)
    horizontal = [p for p in polys if len(p) == 9 and np.all(p[:, 1] == 5.0)]
    assert len(horizontal) == 1, [p.tolist() for p in polys]
    assert horizontal[0][0].tolist() == [1.0, 5.0]
    assert horizontal[0][-1].tolist() == [9.0, 5.0]


def test_empty_skeleton() -> None:
    assert geometry.trace_skeleton(np.zeros((5, 5), dtype=np.uint8)) == []
