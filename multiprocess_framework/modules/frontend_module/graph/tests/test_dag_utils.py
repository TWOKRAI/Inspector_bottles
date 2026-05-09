"""FW-тесты для frontend_module.graph.dag_utils."""
import pytest

from multiprocess_framework.modules.frontend_module.graph.dag_utils import (
    find_connected_edges,
    has_cycle,
    topological_sort,
    validate_port_compatibility,
)


# ---- has_cycle ---- #


class TestHasCycle:
    def test_empty_graph_no_cycle(self):
        """Пустой граф — цикла нет."""
        assert has_cycle([]) is False

    def test_simple_dag_no_cycle(self):
        """Линейный граф A→B→C — цикла нет."""
        edges = [("A", "B"), ("B", "C")]
        assert has_cycle(edges) is False

    def test_simple_cycle_detected(self):
        """A→B→C→A — цикл."""
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        assert has_cycle(edges) is True

    def test_self_loop_is_cycle(self):
        """A→A — цикл."""
        assert has_cycle([("A", "A")]) is True

    def test_new_edge_creates_cycle(self):
        """Добавление ребра создаёт цикл."""
        edges = [("A", "B"), ("B", "C")]
        assert has_cycle(edges, new_edge=("C", "A")) is True

    def test_new_edge_no_cycle(self):
        """Добавление ребра — цикла не создаёт."""
        edges = [("A", "B")]
        assert has_cycle(edges, new_edge=("B", "C")) is False

    def test_diamond_dag_no_cycle(self):
        """A→B, A→C, B→D, C→D — ромбовидный DAG, цикла нет."""
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        assert has_cycle(edges) is False

    def test_disconnected_graph_with_cycle(self):
        """Граф с несколькими компонентами, одна содержит цикл."""
        edges = [("X", "Y"), ("A", "B"), ("B", "A")]
        assert has_cycle(edges) is True


# ---- topological_sort ---- #


class TestTopologicalSort:
    def test_empty_graph(self):
        """Пустой граф — пустой результат."""
        result = topological_sort(set(), [])
        assert result == []

    def test_single_node(self):
        """Один узел без рёбер."""
        result = topological_sort({"A"}, [])
        assert result == ["A"]

    def test_linear_order(self):
        """A→B→C — порядок [A, B, C]."""
        nodes = {"A", "B", "C"}
        edges = [("A", "B"), ("B", "C")]
        result = topological_sort(nodes, edges)
        assert result.index("A") < result.index("B") < result.index("C")

    def test_cycle_returns_empty(self):
        """Граф с циклом — пустой результат."""
        nodes = {"A", "B", "C"}
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        result = topological_sort(nodes, edges)
        assert result == []

    def test_diamond_topology(self):
        """A→B, A→C, B→D, C→D — A первый, D последний."""
        nodes = {"A", "B", "C", "D"}
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        result = topological_sort(nodes, edges)
        assert len(result) == 4
        assert result.index("A") < result.index("D")

    def test_ignores_unknown_nodes_in_edges(self):
        """Рёбра с неизвестными узлами игнорируются."""
        nodes = {"A", "B"}
        edges = [("A", "B"), ("B", "UNKNOWN")]
        result = topological_sort(nodes, edges)
        assert set(result) == {"A", "B"}


# ---- validate_port_compatibility ---- #


class TestValidatePortCompatibility:
    def test_exact_match(self):
        """Точное совпадение dtype."""
        assert validate_port_compatibility("image/bgr", "image/bgr") is True

    def test_any_src_matches_all(self):
        """'any' на источнике совместим с любым dtype."""
        assert validate_port_compatibility("any", "image/bgr") is True
        assert validate_port_compatibility("any", "tensor/float32") is True

    def test_any_tgt_matches_all(self):
        """'any' на назначении совместим с любым dtype."""
        assert validate_port_compatibility("image/bgr", "any") is True

    def test_wildcard_tgt(self):
        """'image/*' на назначении принимает 'image/bgr'."""
        assert validate_port_compatibility("image/bgr", "image/*") is True

    def test_wildcard_src(self):
        """'image/*' на источнике совместим с 'image/bgr'."""
        assert validate_port_compatibility("image/*", "image/bgr") is True

    def test_incompatible_dtypes(self):
        """Несовместимые типы."""
        assert validate_port_compatibility("image/bgr", "tensor/float32") is False

    def test_legacy_output_to_input(self):
        """Legacy: output→input = True."""
        assert validate_port_compatibility("output", "input") is True

    def test_legacy_input_to_output(self):
        """Legacy: input→output = False."""
        assert validate_port_compatibility("input", "output") is False

    def test_wildcard_no_false_match(self):
        """'audio/*' не совместим с 'image/bgr'."""
        assert validate_port_compatibility("image/bgr", "audio/*") is False


# ---- find_connected_edges ---- #


class TestFindConnectedEdges:
    def test_finds_source_edges(self):
        """Находит рёбра где узел является источником."""
        edges = [("A", "B"), ("A", "C"), ("D", "E")]
        result = find_connected_edges(edges, "A")
        assert ("A", "B") in result
        assert ("A", "C") in result
        assert ("D", "E") not in result

    def test_finds_target_edges(self):
        """Находит рёбра где узел является назначением."""
        edges = [("A", "B"), ("C", "B"), ("D", "E")]
        result = find_connected_edges(edges, "B")
        assert ("A", "B") in result
        assert ("C", "B") in result

    def test_empty_for_isolated_node(self):
        """Для изолированного узла — пустой список."""
        edges = [("A", "B")]
        result = find_connected_edges(edges, "C")
        assert result == []
