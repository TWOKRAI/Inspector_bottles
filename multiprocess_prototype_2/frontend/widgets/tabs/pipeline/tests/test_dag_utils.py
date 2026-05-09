"""Тесты dag_utils — универсальные DAG-алгоритмы."""
from __future__ import annotations

import pytest

from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.dag_utils import (
    find_connected_edges,
    has_cycle,
    topological_sort,
    validate_port_compatibility,
)


# ---- has_cycle ---- #


class TestHasCycle:
    """Тесты детекции циклов."""

    def test_no_cycle(self) -> None:
        """Линейный граф A->B->C не содержит цикл."""
        edges = [("A", "B"), ("B", "C")]
        assert has_cycle(edges) is False

    def test_has_cycle(self) -> None:
        """A->B->C->A — цикл."""
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        assert has_cycle(edges) is True

    def test_new_edge_creates_cycle(self) -> None:
        """Добавление ребра C->A создаёт цикл в A->B->C."""
        edges = [("A", "B"), ("B", "C")]
        assert has_cycle(edges, new_edge=("C", "A")) is True

    def test_new_edge_no_cycle(self) -> None:
        """Добавление ребра A->C не создаёт цикл в A->B->C."""
        edges = [("A", "B"), ("B", "C")]
        assert has_cycle(edges, new_edge=("A", "C")) is False

    def test_empty_graph(self) -> None:
        """Пустой граф — нет цикла."""
        assert has_cycle([]) is False

    def test_single_edge(self) -> None:
        """Одно ребро — нет цикла."""
        assert has_cycle([("A", "B")]) is False


# ---- topological_sort ---- #


class TestTopologicalSort:
    """Тесты топологической сортировки."""

    def test_linear(self) -> None:
        """A->B->C -> [A, B, C]."""
        nodes = {"A", "B", "C"}
        edges = [("A", "B"), ("B", "C")]
        result = topological_sort(nodes, edges)
        assert result == ["A", "B", "C"]

    def test_diamond(self) -> None:
        """Diamond DAG: A->{B,C}->D."""
        nodes = {"A", "B", "C", "D"}
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        result = topological_sort(nodes, edges)
        # A должен быть первым, D — последним
        assert result[0] == "A"
        assert result[-1] == "D"
        # B и C перед D
        assert result.index("B") < result.index("D")
        assert result.index("C") < result.index("D")

    def test_cycle_returns_empty(self) -> None:
        """Граф с циклом -> пустой список."""
        nodes = {"A", "B", "C"}
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        result = topological_sort(nodes, edges)
        assert result == []

    def test_isolated_nodes(self) -> None:
        """Изолированные ноды — в результате, отсортированы."""
        nodes = {"A", "B", "C"}
        edges: list[tuple[str, str]] = []
        result = topological_sort(nodes, edges)
        assert set(result) == {"A", "B", "C"}
        assert len(result) == 3


# ---- validate_port_compatibility ---- #


class TestValidatePortCompatibility:
    """Тесты совместимости портов."""

    def test_output_to_input(self) -> None:
        assert validate_port_compatibility("output", "input") is True

    def test_input_to_output(self) -> None:
        assert validate_port_compatibility("input", "output") is False

    def test_output_to_output(self) -> None:
        assert validate_port_compatibility("output", "output") is False


# ---- find_connected_edges ---- #


class TestFindConnectedEdges:
    """Тесты поиска связанных рёбер."""

    def test_find_connected_edges(self) -> None:
        """Найти все рёбра узла B в A->B->C."""
        edges = [("A", "B"), ("B", "C"), ("C", "D")]
        result = find_connected_edges(edges, "B")
        assert ("A", "B") in result
        assert ("B", "C") in result
        assert ("C", "D") not in result
        assert len(result) == 2

    def test_no_connected_edges(self) -> None:
        """Узел без рёбер."""
        edges = [("A", "B"), ("B", "C")]
        result = find_connected_edges(edges, "Z")
        assert result == []
