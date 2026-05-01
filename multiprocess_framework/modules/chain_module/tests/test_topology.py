"""Тесты топологической сортировки и анализа графа."""
from __future__ import annotations

import pytest

from multiprocess_framework.modules.chain_module.graph.topology import is_nonlinear_graph, topological_sort

from .conftest import FakeConnection, FakeNode


def make_nodes(*specs) -> dict:
    """Вспомогательная функция: specs = (node_id, [input_sources])."""
    nodes = {}
    for spec in specs:
        node_id, sources = spec[0], spec[1] if len(spec) > 1 else []
        inputs = [FakeConnection(s) for s in sources]
        nodes[node_id] = FakeNode(node_id=node_id, inputs=inputs)
    return nodes


class TestTopologicalSort:
    def test_single_node(self):
        nodes = make_nodes(("a",))
        result = topological_sort(nodes)
        assert [n.node_id for n in result] == ["a"]

    def test_linear_chain(self):
        nodes = make_nodes(("a",), ("b", ["a"]), ("c", ["b"]))
        result = topological_sort(nodes)
        ids = [n.node_id for n in result]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_empty_graph(self):
        result = topological_sort({})
        assert result == []

    def test_parallel_roots(self):
        # a и b независимы, c зависит от обоих
        nodes = make_nodes(("a",), ("b",), ("c", ["a", "b"]))
        result = topological_sort(nodes)
        ids = [n.node_id for n in result]
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("c")
        assert len(ids) == 3

    def test_diamond_graph(self):
        # a → b, a → c, b → d, c → d
        nodes = make_nodes(("a",), ("b", ["a"]), ("c", ["a"]), ("d", ["b", "c"]))
        result = topological_sort(nodes)
        ids = [n.node_id for n in result]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_external_source_ignored(self):
        # "frame" — внешний источник, не в nodes — игнорируется
        nodes = make_nodes(("a", ["frame"]), ("b", ["a"]))
        result = topological_sort(nodes)
        ids = [n.node_id for n in result]
        assert ids.index("a") < ids.index("b")
        assert len(ids) == 2

    def test_cycle_raises_value_error(self):
        # a → b → a
        nodes = make_nodes(("a", ["b"]), ("b", ["a"]))
        with pytest.raises(ValueError, match="цикл"):
            topological_sort(nodes)

    def test_all_nodes_present_in_result(self):
        nodes = make_nodes(("x",), ("y", ["x"]), ("z", ["x"]))
        result = topological_sort(nodes)
        assert {n.node_id for n in result} == {"x", "y", "z"}


class TestIsNonlinearGraph:
    def test_single_node_is_linear(self):
        nodes = make_nodes(("a",))
        assert is_nonlinear_graph(nodes) is False

    def test_linear_chain_is_linear(self):
        nodes = make_nodes(("a",), ("b", ["a"]), ("c", ["b"]))
        assert is_nonlinear_graph(nodes) is False

    def test_fan_out_is_nonlinear(self):
        # a → b, a → c (fan-out)
        nodes = make_nodes(("a",), ("b", ["a"]), ("c", ["a"]))
        assert is_nonlinear_graph(nodes) is True

    def test_fan_in_is_nonlinear(self):
        # a, b → c (merge)
        nodes = make_nodes(("a",), ("b",), ("c", ["a", "b"]))
        assert is_nonlinear_graph(nodes) is True

    def test_diamond_is_nonlinear(self):
        nodes = make_nodes(("a",), ("b", ["a"]), ("c", ["a"]), ("d", ["b", "c"]))
        assert is_nonlinear_graph(nodes) is True

    def test_empty_graph_is_linear(self):
        assert is_nonlinear_graph({}) is False
