"""Тесты SugiyamaLayout — автоматическая раскладка DAG."""
from __future__ import annotations

from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.layout import (
    GRID_SIZE,
    auto_layout,
)


class TestAutoLayout:
    """Тесты auto_layout."""

    def test_empty_graph(self) -> None:
        """Пустой граф -> пустой dict."""
        result = auto_layout([], [])
        assert result == {}

    def test_linear_graph(self) -> None:
        """3 ноды в ряд: A->B->C — разные X, одинаковый Y."""
        nodes = ["A", "B", "C"]
        edges = [("A", "B"), ("B", "C")]
        positions = auto_layout(nodes, edges)

        assert len(positions) == 3
        # Все 3 ноды присутствуют
        assert "A" in positions
        assert "B" in positions
        assert "C" in positions

        # A на layer 0, B на layer 1, C на layer 2 — x-координаты растут
        assert positions["A"][0] < positions["B"][0]
        assert positions["B"][0] < positions["C"][0]

        # Все на одной высоте (одна нода в каждом слое)
        assert positions["A"][1] == positions["B"][1]
        assert positions["B"][1] == positions["C"][1]

    def test_diamond_graph(self) -> None:
        """Ромбовидный DAG: A->{B,C}->D."""
        nodes = ["A", "B", "C", "D"]
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        positions = auto_layout(nodes, edges)

        assert len(positions) == 4

        # A на layer 0 (самый левый), D на layer 2 (самый правый)
        assert positions["A"][0] < positions["D"][0]

        # B и C на одном layer (1) — одинаковая X
        assert positions["B"][0] == positions["C"][0]

        # B и C на промежуточном layer
        assert positions["A"][0] < positions["B"][0]
        assert positions["B"][0] < positions["D"][0]

        # B и C на разной Y (два узла в одном слое)
        assert positions["B"][1] != positions["C"][1]

    def test_isolated_nodes(self) -> None:
        """Изолированные ноды размещаются в отдельном столбце справа."""
        nodes = ["A", "B", "C", "iso1", "iso2"]
        edges = [("A", "B"), ("B", "C")]
        positions = auto_layout(nodes, edges)

        assert len(positions) == 5

        # Изолированные ноды правее всех connected
        max_connected_x = max(positions[n][0] for n in ["A", "B", "C"])
        assert positions["iso1"][0] > max_connected_x
        assert positions["iso2"][0] > max_connected_x

        # Оба изолированных на одном X
        assert positions["iso1"][0] == positions["iso2"][0]

    def test_grid_snap(self) -> None:
        """Все координаты кратны GRID_SIZE."""
        nodes = ["A", "B", "C", "D"]
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        positions = auto_layout(nodes, edges)

        for nid, (x, y) in positions.items():
            assert x % GRID_SIZE == 0, f"{nid}: x={x} не кратно {GRID_SIZE}"
            assert y % GRID_SIZE == 0, f"{nid}: y={y} не кратно {GRID_SIZE}"

    def test_single_node(self) -> None:
        """Одна нода без рёбер — изолированная, размещается."""
        positions = auto_layout(["only"], [])
        assert len(positions) == 1
        assert "only" in positions

    def test_non_negative_coordinates(self) -> None:
        """Все координаты >= 0."""
        nodes = ["A", "B", "C", "D", "E"]
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"), ("D", "E")]
        positions = auto_layout(nodes, edges)

        for nid, (x, y) in positions.items():
            assert x >= 0, f"{nid}: x={x} отрицательная"
            assert y >= 0, f"{nid}: y={y} отрицательная"
