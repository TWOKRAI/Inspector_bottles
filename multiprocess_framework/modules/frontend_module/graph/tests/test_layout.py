"""FW-тесты для frontend_module.graph.layout."""

from multiprocess_framework.modules.frontend_module.graph.layout import (
    GRID_SIZE,
    _snap_to_grid,
    auto_layout,
)


class TestAutoLayout:
    def test_empty_nodes_returns_empty(self):
        """Пустой список узлов — пустой результат."""
        result = auto_layout([], [])
        assert result == {}

    def test_single_node_gets_position(self):
        """Один изолированный узел получает позицию."""
        result = auto_layout(["A"], [])
        assert "A" in result
        x, y = result["A"]
        assert x >= 0
        assert y >= 0

    def test_all_nodes_have_positions(self):
        """Все переданные узлы получают позиции."""
        nodes = ["A", "B", "C", "D"]
        edges = [("A", "B"), ("B", "C"), ("A", "D")]
        result = auto_layout(nodes, edges)
        assert set(result.keys()) == set(nodes)

    def test_positions_snapped_to_grid(self):
        """Все позиции кратны GRID_SIZE."""
        nodes = ["A", "B", "C"]
        edges = [("A", "B"), ("B", "C")]
        result = auto_layout(nodes, edges)
        for nid, (x, y) in result.items():
            assert x % GRID_SIZE == 0, f"x={x} для {nid} не кратно {GRID_SIZE}"
            assert y % GRID_SIZE == 0, f"y={y} для {nid} не кратно {GRID_SIZE}"

    def test_positions_non_negative(self):
        """Все позиции >= 0."""
        nodes = ["A", "B", "C", "D", "E"]
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "E")]
        result = auto_layout(nodes, edges)
        for nid, (x, y) in result.items():
            assert x >= 0, f"x={x} для {nid} отрицательный"
            assert y >= 0, f"y={y} для {nid} отрицательный"

    def test_cyclic_graph_still_returns_positions(self):
        """Циклический граф — все узлы всё равно получают позиции (fallback)."""
        nodes = ["A", "B", "C"]
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        result = auto_layout(nodes, edges)
        assert set(result.keys()) == {"A", "B", "C"}

    def test_layered_order_respected(self):
        """Узлы в разных слоях имеют разные X-координаты."""
        nodes = ["A", "B", "C"]
        edges = [("A", "B"), ("B", "C")]
        result = auto_layout(nodes, edges)
        # A — layer 0, B — layer 1, C — layer 2 → разные X
        assert result["A"][0] < result["B"][0] < result["C"][0]

    def test_custom_spacing(self):
        """Кастомные h_spacing/v_spacing применяются корректно."""
        nodes = ["A", "B"]
        edges = [("A", "B")]
        default_result = auto_layout(nodes, edges)
        custom_result = auto_layout(nodes, edges, h_spacing=200)
        # При большем h_spacing разница X должна быть больше
        default_gap = abs(default_result["B"][0] - default_result["A"][0])
        custom_gap = abs(custom_result["B"][0] - custom_result["A"][0])
        assert custom_gap > default_gap


class TestSnapToGrid:
    def test_exact_grid_value(self):
        """Значение, уже кратное grid — не меняется."""
        assert _snap_to_grid(100.0) == 100.0

    def test_round_up(self):
        """Значение ближе к верхней границе — округляется вверх."""
        assert _snap_to_grid(15.0) == 20.0

    def test_round_down(self):
        """Значение ближе к нижней границе — округляется вниз."""
        assert _snap_to_grid(5.0) == 0.0

    def test_zero_stays_zero(self):
        """Ноль остаётся нулём."""
        assert _snap_to_grid(0.0) == 0.0
