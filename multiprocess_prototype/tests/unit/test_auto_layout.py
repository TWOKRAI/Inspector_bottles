"""Тесты для auto_layout — алгоритм Sugiyama layered layout.

Тестируется чистая функция. PySide6 нужен только транзитивно
(constants.py импортирует QColor) — берётся из venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем multiprocess_prototype/ в sys.path для коротких импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.widgets.pipeline.pipeline_tab.canvas.auto_layout import auto_layout  # noqa: E402, I001
from frontend.widgets.pipeline.pipeline_tab.views._layout_constants import GRID_SIZE  # noqa: E402
from registers.pipeline.processing_node import NodeInput, ProcessingNode  # noqa: E402


# ---------------------------------------------------------------------------
# Утилиты для создания тестовых графов
# ---------------------------------------------------------------------------


def _make_node(node_id: str, sources: list[str] | None = None) -> ProcessingNode:
    """Создать ProcessingNode с указанными зависимостями."""
    inputs = []
    if sources:
        for src in sources:
            inputs.append(NodeInput(source=src, output_port="out", input_port="in"))
    return ProcessingNode(
        node_id=node_id,
        operation_ref="dummy_op",
        inputs=inputs,
    )


def _make_graph(spec: dict[str, list[str]]) -> dict[str, ProcessingNode]:
    """Создать граф из спецификации {node_id: [source_ids]}.

    Пример: {"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]}
    """
    return {nid: _make_node(nid, sources) for nid, sources in spec.items()}


# ---------------------------------------------------------------------------
# Тест: пустой граф
# ---------------------------------------------------------------------------


def test_empty_graph():
    """Пустой граф → пустой результат."""
    result = auto_layout({})
    assert result == {}


# ---------------------------------------------------------------------------
# Тест: одна нода
# ---------------------------------------------------------------------------


def test_single_node():
    """Одна изолированная нода → позиция (0, 0)."""
    nodes = _make_graph({"A": []})
    result = auto_layout(nodes)
    assert "A" in result
    x, y = result["A"]
    assert x == 0
    assert y == 0


# ---------------------------------------------------------------------------
# Тест: линейная цепочка A→B→C
# ---------------------------------------------------------------------------


def test_linear_chain():
    """Линейная цепочка A→B→C → 3 слоя, один узел в каждом.

    Проверяем что X возрастает (LR direction) и Y одинаковый.
    """
    nodes = _make_graph({"A": [], "B": ["A"], "C": ["B"]})
    result = auto_layout(nodes)

    assert len(result) == 3
    xa, ya = result["A"]
    xb, yb = result["B"]
    xc, yc = result["C"]

    # X строго возрастает: A < B < C
    assert xa < xb < xc

    # Y одинаковый (все в одном ряду)
    assert ya == yb == yc


# ---------------------------------------------------------------------------
# Тест: DAG с ветвлением A→{B,C}→D
# ---------------------------------------------------------------------------


def test_dag_with_branching():
    """DAG A→{B,C}→D → 3 слоя: A на 0-м, B и C на 1-м, D на 2-м."""
    nodes = _make_graph({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]})
    result = auto_layout(nodes)

    assert len(result) == 4

    xa, _ = result["A"]
    xb, _ = result["B"]
    xc, _ = result["C"]
    xd, _ = result["D"]

    # A на первом слое, B и C на втором, D на третьем
    assert xa < xb
    assert xa < xc
    assert xb == xc  # B и C на одном слое
    assert xb < xd


# ---------------------------------------------------------------------------
# Тест: изолированные узлы
# ---------------------------------------------------------------------------


def test_isolated_nodes():
    """Изолированные узлы (без связей) → отдельный столбец."""
    nodes = _make_graph({"A": [], "B": ["A"], "X": [], "Y": []})
    result = auto_layout(nodes)

    assert len(result) == 4

    xa, _ = result["A"]
    xb, _ = result["B"]
    xx, _ = result["X"]
    xy, _ = result["Y"]

    # A→B — связанная цепочка, X и Y — изолированные
    # Изолированные должны быть правее связанных нод
    assert xx > xb
    assert xy > xb
    # Изолированные в одном столбце
    assert xx == xy


# ---------------------------------------------------------------------------
# Тест: snap-to-grid
# ---------------------------------------------------------------------------


def test_snap_to_grid():
    """Все позиции должны быть кратны GRID_SIZE."""
    nodes = _make_graph({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]})
    result = auto_layout(nodes)

    for node_id, (x, y) in result.items():
        assert x % GRID_SIZE == 0, f"X({node_id})={x} не кратен {GRID_SIZE}"
        assert y % GRID_SIZE == 0, f"Y({node_id})={y} не кратен {GRID_SIZE}"


# ---------------------------------------------------------------------------
# Тест: неотрицательные координаты
# ---------------------------------------------------------------------------


def test_non_negative_positions():
    """Все координаты >= 0."""
    nodes = _make_graph({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"], "E": ["D"]})
    result = auto_layout(nodes)

    for node_id, (x, y) in result.items():
        assert x >= 0, f"X({node_id})={x} отрицательный"
        assert y >= 0, f"Y({node_id})={y} отрицательный"


# ---------------------------------------------------------------------------
# Тест: множественные источники (diamond shape)
# ---------------------------------------------------------------------------


def test_diamond_dag():
    """Diamond: A→B, A→C, B→D, C→D. Слои: A(0), {B,C}(1), D(2)."""
    nodes = _make_graph({"A": [], "B": ["A"], "C": ["A"], "D": ["B", "C"]})
    result = auto_layout(nodes)

    xa, _ = result["A"]
    xb, _ = result["B"]
    xc, _ = result["C"]
    xd, _ = result["D"]

    assert xb == xc  # один слой
    assert xa < xb < xd


# ---------------------------------------------------------------------------
# Тест: два несвязанных подграфа
# ---------------------------------------------------------------------------


def test_two_disconnected_subgraphs():
    """Два независимых подграфа A→B и C→D — оба раскладываются."""
    nodes = _make_graph({"A": [], "B": ["A"], "C": [], "D": ["C"]})
    result = auto_layout(nodes)

    assert len(result) == 4
    xa, _ = result["A"]
    xb, _ = result["B"]
    xc, _ = result["C"]
    xd, _ = result["D"]

    # Оба подграфа имеют 2 слоя
    assert xa < xb
    assert xc < xd
    # Корневые ноды на одном слое
    assert xa == xc


# ---------------------------------------------------------------------------
# Тест: широкий граф (много нод на одном слое)
# ---------------------------------------------------------------------------


def test_wide_graph():
    """A→{B,C,D,E} → 2 слоя, 4 ноды на втором слое."""
    nodes = _make_graph({"A": [], "B": ["A"], "C": ["A"], "D": ["A"], "E": ["A"]})
    result = auto_layout(nodes)

    xa, _ = result["A"]
    # Все зависимые на одном слое
    x_values = {result[nid][0] for nid in ["B", "C", "D", "E"]}
    assert len(x_values) == 1  # один X для всех
    assert xa < x_values.pop()

    # Y координаты все различные (4 ноды в столбце)
    y_values = [result[nid][1] for nid in ["B", "C", "D", "E"]]
    assert len(set(y_values)) == 4


# ---------------------------------------------------------------------------
# Тест: source="frame" не создаёт зависимость
# ---------------------------------------------------------------------------


def test_frame_source_ignored():
    """Узел с source="frame" (не в графе) → трактуется как корневой (слой 0)."""
    nodes = {
        "A": ProcessingNode(
            node_id="A",
            operation_ref="op",
            inputs=[NodeInput(source="frame", output_port="out")],
        ),
        "B": _make_node("B", ["A"]),
    }
    result = auto_layout(nodes)

    xa, _ = result["A"]
    xb, _ = result["B"]
    assert xa < xb  # A — слой 0, B — слой 1
