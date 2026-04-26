"""Phase 8 smoke-тесты — интеграция всех компонентов Phase 8.

Сценарии:
1. Обратная совместимость Phase 5 — каталог без портов получает дефолты
2. Линейная цепочка → ChainRunnable (backward compat)
3. DAG с ветвлением и merge → DagRunnable
4. Linearity check (is_linear, get_linearity_warning)
5. Auto-layout (Sugiyama) вычисляет позиции с snap-to-grid
6. ActionBuilder + GraphActionHandler round-trip (execute → undo → redo)
7. Валидация несовместимых портов в builder
8. NodeInput.input_port backward compat (default = "in")
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# sys.path: Inspector_prototype/ + multiprocess_prototype_v3/
# conftest.py уже добавляет их, но для надёжности дублируем
# ---------------------------------------------------------------------------
_V3_ROOT = Path(__file__).resolve().parents[2]  # multiprocess_prototype_v3/
_INSPECTOR_ROOT = Path(__file__).resolve().parents[3]  # Inspector_prototype/
for _p in (_INSPECTOR_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ---------------------------------------------------------------------------
# PyQt5 mock: auto_layout и linearity_check используют constants.py с QColor
# ---------------------------------------------------------------------------
if "PyQt5" not in sys.modules:
    sys.modules["PyQt5"] = MagicMock()
    sys.modules["PyQt5.QtGui"] = MagicMock()
    sys.modules["PyQt5.QtCore"] = MagicMock()
    sys.modules["PyQt5.QtWidgets"] = MagicMock()

from frontend.actions.builder import ActionBuilder  # noqa: E402, I001
from frontend.actions.default_bus_factory import create_default_action_bus  # noqa: E402
from multiprocess_prototype_v3.frontend.widgets.pipeline_tab.auto_layout import (  # noqa: E402
    auto_layout,
)
from multiprocess_prototype_v3.frontend.widgets.pipeline_tab.linearity_check import (  # noqa: E402
    get_linearity_warning,
    is_linear,
)
from multiprocess_prototype_v3.registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from multiprocess_prototype_v3.registers.processor.catalog.loader import (  # noqa: E402
    load_catalog,
)
from multiprocess_prototype_v3.registers.processor.catalog.port_types import (  # noqa: E402
    PORT_TYPE_IMAGE,
    PORT_TYPE_MASK,
    are_ports_compatible,
)
from multiprocess_prototype_v3.registers.processor.catalog.schemas import (  # noqa: E402
    Port,
    ProcessingOperationDef,
)
from multiprocess_prototype_v3.services.processor.chain.autofill import (  # noqa: E402
    autofill_inputs,
)
from multiprocess_prototype_v3.services.processor.chain.builder import (  # noqa: E402
    GraphRunnableBuilder,
)
from multiprocess_prototype_v3.services.processor.chain.runnable import (  # noqa: E402
    ChainResult,
)
from multiprocess_prototype_v3.services.processor.operations.loader import (  # noqa: E402
    clear_cache,
)

# Путь к seed-файлу каталога (внутри multiprocess_prototype_v3/data/)
_SEED_CATALOG = _V3_ROOT / "data" / "processing_catalog.yaml"

# Цветовой диапазон для красного объекта (BGR: B=0-50, G=0-50, R=150-255)
_RED_LOWER = [0, 0, 150]
_RED_UPPER = [50, 50, 255]


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_operation_cache():
    """Сбросить кэш загрузчика операций перед каждым тестом."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def seed_catalog() -> dict[str, ProcessingOperationDef]:
    """Реальный каталог из seed-файла."""
    return load_catalog(_SEED_CATALOG)


@pytest.fixture
def red_frame() -> np.ndarray:
    """Синтетический кадр 100x100 с красным прямоугольником в центре."""
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[30:70, 30:70] = [0, 0, 200]  # BGR: red channel = 200
    return frame


@pytest.fixture
def custom_catalog() -> dict[str, ProcessingOperationDef]:
    """Кастомный каталог для DAG-тестов.

    Содержит операции из seed + merge-операцию с двумя входами.
    """
    catalog = load_catalog(_SEED_CATALOG)

    # Добавляем merge-операцию с двумя входными портами
    merge_op = ProcessingOperationDef(
        name="Merge (тестовый)",
        type_key="merge_test",
        params_schema="registers.processor.processings.color_detection.ColorDetectionParams",
        module_path="services.processor.operations.color_detection_op.ColorDetectionOp",
        on_error="skip",
        description="Тестовая merge-операция с двумя входами",
        input_ports=[
            Port(name="in1", data_type=PORT_TYPE_IMAGE),
            Port(name="in2", data_type=PORT_TYPE_IMAGE),
        ],
        output_ports=[
            Port(name="out", data_type=PORT_TYPE_IMAGE),
        ],
    )
    catalog["merge_test"] = merge_op
    return catalog


# ---------------------------------------------------------------------------
# Мок RegistersManager (для Action-тестов)
# ---------------------------------------------------------------------------


class MockRM:
    """Мок RegistersManager без Qt и реальной БД."""

    def __init__(self):
        self._data: dict = {}
        self.calls: list = []

    def set_field_value(self, register_name, field_name, value):
        self._data[(register_name, field_name)] = value
        self.calls.append((register_name, field_name, value))
        return (True, None)

    def get_field_value(self, register_name, field_name):
        return self._data.get((register_name, field_name))

    def get_register(self, register_name):
        return None

    def model_dump_all(self):
        result = {}
        for (reg, field), val in self._data.items():
            result.setdefault(reg, {})[field] = val
        return result


# ===========================================================================
# Smoke-тест 1: Обратная совместимость Phase 5 — каталог без портов
# ===========================================================================


class TestCatalogDefaultPorts:
    """YAML-каталог Phase 5 загружается, операции получают default порты."""

    def test_catalog_has_default_input_ports(self, seed_catalog):
        """Каждая операция в seed-каталоге имеет хотя бы один входной порт."""
        assert len(seed_catalog) > 0, "Каталог пуст — проверь путь к seed-файлу"
        for type_key, op_def in seed_catalog.items():
            assert len(op_def.input_ports) >= 1, f"Операция '{type_key}' не имеет входных портов"

    def test_catalog_has_default_output_ports(self, seed_catalog):
        """Каждая операция в seed-каталоге имеет хотя бы один выходной порт."""
        for type_key, op_def in seed_catalog.items():
            assert len(op_def.output_ports) >= 1, f"Операция '{type_key}' не имеет выходных портов"

    def test_catalog_default_port_names(self, seed_catalog):
        """Default порты имеют имена 'in' и 'out'."""
        for type_key, op_def in seed_catalog.items():
            input_names = [p.name for p in op_def.input_ports]
            output_names = [p.name for p in op_def.output_ports]
            assert "in" in input_names, (
                f"Операция '{type_key}': нет входного порта 'in', есть: {input_names}"
            )
            assert "out" in output_names, (
                f"Операция '{type_key}': нет выходного порта 'out', есть: {output_names}"
            )

    def test_catalog_default_port_data_type(self, seed_catalog):
        """Default порты имеют data_type='image'."""
        for type_key, op_def in seed_catalog.items():
            for port in op_def.input_ports:
                if port.name == "in":
                    assert port.data_type == PORT_TYPE_IMAGE, (
                        f"Операция '{type_key}': порт 'in' — тип '{port.data_type}', ожидался 'image'"
                    )
            for port in op_def.output_ports:
                if port.name == "out":
                    assert port.data_type == PORT_TYPE_IMAGE, (
                        f"Операция '{type_key}': порт 'out' — тип '{port.data_type}', ожидался 'image'"
                    )


# ===========================================================================
# Smoke-тест 2: Phase 5 линейная цепочка → ChainRunnable
# ===========================================================================


class TestPhase5LinearChainBackwardCompat:
    """Линейная цепочка из Phase 5 продолжает работать через ChainRunnable."""

    def test_linear_chain_returns_chain_runnable(self, seed_catalog):
        """Линейная цепочка из 2 нод → ChainRunnable (не DagRunnable)."""
        node1 = ProcessingNode(operation_ref="color_detection")
        node2 = ProcessingNode(operation_ref="blob_detection")

        nodes_raw = {node1.node_id: node1, node2.node_id: node2}
        nodes = autofill_inputs(nodes_raw)

        result = GraphRunnableBuilder.build(nodes, seed_catalog)
        assert type(result).__name__ == "ChainRunnable", (
            f"Ожидался ChainRunnable, получили {type(result).__name__}"
        )

    def test_linear_chain_has_two_steps(self, seed_catalog):
        """ChainRunnable содержит 2 шага."""
        node1 = ProcessingNode(operation_ref="color_detection")
        node2 = ProcessingNode(operation_ref="blob_detection")

        nodes_raw = {node1.node_id: node1, node2.node_id: node2}
        nodes = autofill_inputs(nodes_raw)

        chain = GraphRunnableBuilder.build(nodes, seed_catalog)
        assert len(chain.steps) == 2

    def test_linear_chain_executes_successfully(self, seed_catalog, red_frame):
        """Линейная цепочка выполняется и возвращает ChainResult."""
        node1 = ProcessingNode(operation_ref="color_detection")
        node2 = ProcessingNode(operation_ref="blob_detection")

        nodes_raw = {node1.node_id: node1, node2.node_id: node2}
        nodes = autofill_inputs(nodes_raw)

        chain = GraphRunnableBuilder.build(nodes, seed_catalog)
        chain.steps[0].operation.configure(
            {
                "color_lower": _RED_LOWER,
                "color_upper": _RED_UPPER,
                "min_area": 100,
                "max_area": 50000,
            }
        )

        result = chain.execute(red_frame, metadata={"camera_id": "cam_0", "region_id": "r0"})
        assert isinstance(result, ChainResult)
        assert result.failed is False


# ===========================================================================
# Smoke-тест 3: DAG ветвление и merge → DagRunnable
# ===========================================================================


class TestDagBranchAndMerge:
    """Граф с ветвлением A→{B,C}→D → DagRunnable, execute корректен."""

    @staticmethod
    def _build_dag_nodes() -> dict[str, ProcessingNode]:
        """Создать DAG: A→{B,C}→D.

        A: color_detection (вход: frame)
        B: color_detection (вход: A)
        C: color_detection (вход: A)
        D: merge_test (входы: B→in1, C→in2)
        """
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="color_detection",
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        node_c = ProcessingNode(
            node_id="c",
            operation_ref="color_detection",
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        node_d = ProcessingNode(
            node_id="d",
            operation_ref="merge_test",
            inputs=[
                NodeInput(source="b", output_port="out", input_port="in1"),
                NodeInput(source="c", output_port="out", input_port="in2"),
            ],
        )
        return {"a": node_a, "b": node_b, "c": node_c, "d": node_d}

    def test_dag_returns_dag_runnable(self, custom_catalog):
        """Граф с ветвлением → DagRunnable."""
        nodes = self._build_dag_nodes()
        result = GraphRunnableBuilder.build(nodes, custom_catalog)
        assert type(result).__name__ == "DagRunnable", (
            f"Ожидался DagRunnable, получили {type(result).__name__}"
        )

    def test_dag_has_four_steps(self, custom_catalog):
        """DagRunnable содержит 4 шага (A, B, C, D)."""
        nodes = self._build_dag_nodes()
        dag = GraphRunnableBuilder.build(nodes, custom_catalog)
        assert len(dag.steps) == 4

    def test_dag_execute_returns_chain_result(self, custom_catalog, red_frame):
        """DagRunnable.execute возвращает ChainResult без ошибок."""
        nodes = self._build_dag_nodes()
        dag = GraphRunnableBuilder.build(nodes, custom_catalog)

        result = dag.execute(red_frame, metadata={"camera_id": "cam_0", "region_id": "r0"})
        assert isinstance(result, ChainResult)
        assert result.failed is False

    def test_dag_execute_has_processing_time(self, custom_catalog, red_frame):
        """DagRunnable.execute записывает processing_time >= 0."""
        nodes = self._build_dag_nodes()
        dag = GraphRunnableBuilder.build(nodes, custom_catalog)

        result = dag.execute(red_frame)
        assert result.processing_time >= 0.0


# ===========================================================================
# Smoke-тест 4: Linearity check
# ===========================================================================


class TestLinearityCheck:
    """Проверка is_linear и get_linearity_warning."""

    def test_linear_chain_is_linear(self):
        """Линейная цепочка A→B → is_linear True."""
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="blob_detection",
            inputs=[NodeInput(source="a")],
        )
        nodes = {"a": node_a, "b": node_b}

        assert is_linear(nodes) is True
        assert get_linearity_warning(nodes) is None

    def test_dag_is_not_linear(self):
        """DAG с ветвлением A→{B,C} → is_linear False, warning не None."""
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="color_detection",
            inputs=[NodeInput(source="a")],
        )
        node_c = ProcessingNode(
            node_id="c",
            operation_ref="color_detection",
            inputs=[NodeInput(source="a")],
        )
        nodes = {"a": node_a, "b": node_b, "c": node_c}

        assert is_linear(nodes) is False
        warning = get_linearity_warning(nodes)
        assert warning is not None
        assert "нелинеен" in warning.lower() or "ветвлен" in warning.lower()

    def test_merge_is_not_linear(self):
        """Граф с merge {A,B}→C → is_linear False."""
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(node_id="b", operation_ref="color_detection", inputs=[])
        node_c = ProcessingNode(
            node_id="c",
            operation_ref="color_detection",
            inputs=[NodeInput(source="a"), NodeInput(source="b")],
        )
        nodes = {"a": node_a, "b": node_b, "c": node_c}

        assert is_linear(nodes) is False


# ===========================================================================
# Smoke-тест 5: Auto-layout
# ===========================================================================


class TestAutoLayoutIntegration:
    """Auto-layout вычисляет позиции для нод."""

    def test_auto_layout_computes_positions(self):
        """auto_layout возвращает позиции для 3 нод."""
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="blob_detection",
            inputs=[NodeInput(source="a")],
        )
        node_c = ProcessingNode(
            node_id="c",
            operation_ref="color_detection",
            inputs=[NodeInput(source="b")],
        )
        nodes = {"a": node_a, "b": node_b, "c": node_c}

        positions = auto_layout(nodes)
        assert len(positions) == 3
        assert set(positions.keys()) == {"a", "b", "c"}

    def test_auto_layout_snap_to_grid(self):
        """Все позиции кратны GRID_SIZE (20)."""
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="blob_detection",
            inputs=[NodeInput(source="a")],
        )
        node_c = ProcessingNode(
            node_id="c",
            operation_ref="color_detection",
            inputs=[NodeInput(source="b")],
        )
        nodes = {"a": node_a, "b": node_b, "c": node_c}

        positions = auto_layout(nodes)
        grid_size = 20
        for node_id, (x, y) in positions.items():
            assert x % grid_size == 0, f"Нода '{node_id}': x={x} не кратно {grid_size}"
            assert y % grid_size == 0, f"Нода '{node_id}': y={y} не кратно {grid_size}"

    def test_auto_layout_preserves_topological_order(self):
        """Ноды в позднем слое имеют большую x-координату."""
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="blob_detection",
            inputs=[NodeInput(source="a")],
        )
        nodes = {"a": node_a, "b": node_b}

        positions = auto_layout(nodes)
        assert positions["a"][0] < positions["b"][0], (
            f"A.x ({positions['a'][0]}) должна быть меньше B.x ({positions['b'][0]})"
        )


# ===========================================================================
# Smoke-тест 6: ActionBuilder + GraphActionHandler round-trip
# ===========================================================================


class TestGraphActionsRoundTrip:
    """graph_connect → execute → undo → redo — round-trip через ActionBus."""

    def test_graph_connect_execute_undo_redo(self):
        """graph_connect → execute записывает nodes_after, undo → nodes_before, redo → nodes_after."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        nodes_before = {"a": {"node_id": "a"}}
        nodes_after = {"a": {"node_id": "a", "inputs": [{"source": "b"}]}}

        action = ActionBuilder.graph_connect(
            region_id="region_1",
            source_node_id="b",
            output_port="out",
            target_node_id="a",
            input_port="in",
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        # Execute
        bus.execute(action)
        assert len(rm.calls) == 1
        assert rm.calls[-1] == ("region_1", "vision_pipeline", nodes_after)

        # Undo
        bus.undo()
        assert len(rm.calls) == 2
        assert rm.calls[-1] == ("region_1", "vision_pipeline", nodes_before)

        # Redo
        bus.redo()
        assert len(rm.calls) == 3
        assert rm.calls[-1] == ("region_1", "vision_pipeline", nodes_after)

    def test_graph_node_add_remove_round_trip(self):
        """graph_node_add → execute → undo → redo."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        nodes_before = {}
        node_data = {"node_id": "new_node", "operation_ref": "color_detection"}
        nodes_after = {"new_node": node_data}

        action = ActionBuilder.graph_node_add(
            region_id="region_1",
            node_data=node_data,
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        bus.execute(action)
        assert rm.calls[-1][2] == nodes_after

        bus.undo()
        assert rm.calls[-1][2] == nodes_before

        bus.redo()
        assert rm.calls[-1][2] == nodes_after

    def test_graph_node_move_coalesce(self):
        """Серия GRAPH_NODE_MOVE с одинаковым coalesce_key → 1 Action в стеке."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        # Три последовательных перемещения одного узла
        move1 = ActionBuilder.graph_node_move("r1", "n1", (0, 0), (10, 10))
        move2 = ActionBuilder.graph_node_move("r1", "n1", (10, 10), (20, 20))
        move3 = ActionBuilder.graph_node_move("r1", "n1", (20, 20), (30, 30))

        bus.execute(move1)
        bus.execute(move2)
        bus.execute(move3)

        # Должен быть 1 Action в undo-стеке (coalesced)
        assert bus.can_undo() is True

        # Undo: backward_patch от первого (old_pos=(0,0))
        bus.undo()
        # После undo одного coalesced действия — стек пуст
        assert bus.can_undo() is False

    def test_graph_disconnect_round_trip(self):
        """graph_disconnect → execute → undo восстанавливает nodes_before."""
        rm = MockRM()
        bus = create_default_action_bus(rm)

        nodes_before = {"a": {"inputs": [{"source": "b"}]}}
        nodes_after = {"a": {"inputs": []}}

        action = ActionBuilder.graph_disconnect(
            region_id="region_1",
            source_node_id="b",
            output_port="out",
            target_node_id="a",
            input_port="in",
            nodes_before=nodes_before,
            nodes_after=nodes_after,
        )

        bus.execute(action)
        assert rm.calls[-1][2] == nodes_after

        bus.undo()
        assert rm.calls[-1][2] == nodes_before


# ===========================================================================
# Smoke-тест 7: Port validation в builder
# ===========================================================================


class TestPortValidation:
    """Несовместимые порты отвергаются builder-ом."""

    def test_incompatible_ports_rejected(self):
        """mask→image: несовместимые порты → ValueError."""
        # Создаём каталог с операцией, выход которой — mask
        mask_output_op = ProcessingOperationDef(
            name="Mask producer",
            type_key="mask_producer",
            params_schema="registers.processor.processings.color_detection.ColorDetectionParams",
            module_path="services.processor.operations.color_detection_op.ColorDetectionOp",
            on_error="skip",
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_MASK)],
        )

        image_input_op = ProcessingOperationDef(
            name="Image consumer",
            type_key="image_consumer",
            params_schema="registers.processor.processings.color_detection.ColorDetectionParams",
            module_path="services.processor.operations.color_detection_op.ColorDetectionOp",
            on_error="skip",
            input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
            output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
        )

        catalog = {
            "mask_producer": mask_output_op,
            "image_consumer": image_input_op,
        }

        # mask → image: несовместимо (mask совместим только с mask и any)
        node_a = ProcessingNode(node_id="a", operation_ref="mask_producer", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_consumer",
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        nodes = {"a": node_a, "b": node_b}

        with pytest.raises(ValueError, match="[Нн]есовместим"):
            GraphRunnableBuilder.build(nodes, catalog)

    def test_compatible_ports_accepted(self, seed_catalog):
        """image→image: совместимые порты — build проходит."""
        node_a = ProcessingNode(node_id="a", operation_ref="color_detection", inputs=[])
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="blob_detection",
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        nodes = {"a": node_a, "b": node_b}

        # Не должно бросать исключение
        result = GraphRunnableBuilder.build(nodes, seed_catalog)
        assert result is not None

    def test_are_ports_compatible_utility(self):
        """Прямая проверка утилиты are_ports_compatible."""
        assert are_ports_compatible("image", "image") is True
        assert are_ports_compatible("image", "any") is True
        assert are_ports_compatible("mask", "image") is False
        assert are_ports_compatible("mask", "mask") is True
        assert are_ports_compatible("any", "image") is True
        assert are_ports_compatible("any", "any") is True
        assert are_ports_compatible("unknown_type", "image") is False


# ===========================================================================
# Smoke-тест 8: NodeInput.input_port backward compat
# ===========================================================================


class TestNodeInputBackwardCompat:
    """NodeInput без явного input_port → default 'in'."""

    def test_node_input_default_input_port(self):
        """NodeInput(source='a') → input_port='in'."""
        inp = NodeInput(source="a")
        assert inp.input_port == "in"

    def test_node_input_default_output_port(self):
        """NodeInput(source='a') → output_port='out'."""
        inp = NodeInput(source="a")
        assert inp.output_port == "out"

    def test_node_input_explicit_ports(self):
        """NodeInput с явными портами сохраняет их."""
        inp = NodeInput(source="a", output_port="mask_out", input_port="mask_in")
        assert inp.output_port == "mask_out"
        assert inp.input_port == "mask_in"

    def test_processing_node_default_position_none(self):
        """ProcessingNode без position → position=None."""
        node = ProcessingNode(operation_ref="color_detection")
        assert node.position is None

    def test_processing_node_with_position(self):
        """ProcessingNode с position сохраняет координаты."""
        node = ProcessingNode(operation_ref="color_detection", position=(100, 200))
        assert node.position == (100, 200)
