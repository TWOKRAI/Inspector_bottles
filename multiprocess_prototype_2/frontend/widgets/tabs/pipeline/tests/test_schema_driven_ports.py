"""Тесты Task 14.1 — Schema-Driven Ports.

Покрывает:
- validate_port_compatibility: any, wildcard, exact match, incompatible
- NodeItem с port_schemas: правильное число портов
- NodeItem без port_schemas: backward compat 1+1
- PipelineModel.add_wire() с type check
- PortSchema dataclass
"""
from __future__ import annotations

import pytest

from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.dag_utils import (
    validate_port_compatibility,
)
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.model import PipelineModel
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.port_schema import PortSchema
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.node_item import NodeData, NodeItem
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.port_item import PortItem


# ------------------------------------------------------------------ #
#  PortSchema dataclass                                               #
# ------------------------------------------------------------------ #

class TestPortSchema:
    """Тесты PortSchema dataclass."""

    def test_port_schema_basic(self) -> None:
        """PortSchema создаётся с обязательными полями."""
        ps = PortSchema(name="frame", direction="input", dtype="image/bgr")
        assert ps.name == "frame"
        assert ps.direction == "input"
        assert ps.dtype == "image/bgr"
        assert ps.optional is False

    def test_port_schema_defaults(self) -> None:
        """PortSchema: dtype по умолчанию 'any', optional=False."""
        ps = PortSchema(name="data", direction="output")
        assert ps.dtype == "any"
        assert ps.optional is False

    def test_port_schema_optional(self) -> None:
        """PortSchema: optional=True работает."""
        ps = PortSchema(name="mask", direction="input", dtype="image/gray", optional=True)
        assert ps.optional is True


# ------------------------------------------------------------------ #
#  validate_port_compatibility                                        #
# ------------------------------------------------------------------ #

class TestValidatePortCompatibilityDtype:
    """Тесты новой dtype-based совместимости портов."""

    def test_exact_match_image_bgr(self) -> None:
        """Точное совпадение image/bgr → True."""
        assert validate_port_compatibility("image/bgr", "image/bgr") is True

    def test_exact_match_tensor(self) -> None:
        """Точное совпадение tensor/float32 → True."""
        assert validate_port_compatibility("tensor/float32", "tensor/float32") is True

    def test_incompatible_different_subtypes(self) -> None:
        """image/bgr → image/gray несовместимо."""
        assert validate_port_compatibility("image/bgr", "image/gray") is False

    def test_any_src_accepts_anything(self) -> None:
        """'any' источник совместим с любым типом."""
        assert validate_port_compatibility("any", "image/bgr") is True
        assert validate_port_compatibility("any", "tensor/float32") is True
        assert validate_port_compatibility("any", "dict") is True

    def test_any_tgt_accepts_anything(self) -> None:
        """Любой тип совместим с 'any' назначением."""
        assert validate_port_compatibility("image/bgr", "any") is True
        assert validate_port_compatibility("tensor/float32", "any") is True

    def test_wildcard_target_accepts_subtype(self) -> None:
        """'image/*' принимает 'image/bgr' и 'image/gray'."""
        assert validate_port_compatibility("image/bgr", "image/*") is True
        assert validate_port_compatibility("image/gray", "image/*") is True

    def test_wildcard_source_compatible_with_subtype(self) -> None:
        """'image/*' источник совместим с 'image/bgr' назначением."""
        assert validate_port_compatibility("image/*", "image/bgr") is True

    def test_wildcard_incompatible_different_family(self) -> None:
        """'image/*' не принимает 'tensor/float32'."""
        assert validate_port_compatibility("tensor/float32", "image/*") is False

    def test_backward_compat_output_input(self) -> None:
        """Backward compat: ('output', 'input') → True."""
        assert validate_port_compatibility("output", "input") is True

    def test_backward_compat_input_output_false(self) -> None:
        """Backward compat: ('input', 'output') → False (несовместимо как dtype)."""
        assert validate_port_compatibility("input", "output") is False

    def test_incompatible_completely_different(self) -> None:
        """Полностью разные типы несовместимы."""
        assert validate_port_compatibility("image/bgr", "tensor/float32") is False

    def test_any_any(self) -> None:
        """'any' → 'any' совместимо."""
        assert validate_port_compatibility("any", "any") is True


# ------------------------------------------------------------------ #
#  NodeItem с port_schemas                                            #
# ------------------------------------------------------------------ #

class TestNodeItemWithPortSchemas:
    """Тесты NodeItem с Schema-Driven Ports."""

    def test_node_with_schemas_correct_port_count(self, qtbot):
        """NodeItem с 2 inputs + 1 output создаёт 2+1 порта."""
        schemas = [
            PortSchema("frame", "input", "image/bgr"),
            PortSchema("mask", "input", "image/gray"),
            PortSchema("result", "output", "image/bgr"),
        ]
        data = NodeData("proc1", "Processor", category="processing")
        item = NodeItem(data, port_schemas=schemas)

        assert len(item.input_ports) == 2
        assert len(item.output_ports) == 1

    def test_node_with_schemas_port_types(self, qtbot):
        """Порты имеют правильный port_type."""
        schemas = [
            PortSchema("frame", "input", "image/bgr"),
            PortSchema("result", "output", "image/bgr"),
        ]
        data = NodeData("proc2", "Processor")
        item = NodeItem(data, port_schemas=schemas)

        assert item.input_ports[0].is_input is True
        assert item.output_ports[0].is_output is True

    def test_node_with_schemas_endpoints(self, qtbot):
        """Endpoint портов содержит node_id и имя порта."""
        schemas = [
            PortSchema("frame", "input", "image/bgr"),
            PortSchema("mask", "output", "image/gray"),
        ]
        data = NodeData("cam1", "Camera")
        item = NodeItem(data, port_schemas=schemas)

        # Input port endpoint = "cam1.frame"
        assert "cam1" in item.input_ports[0].endpoint
        assert "frame" in item.input_ports[0].endpoint
        # Output port endpoint = "cam1.mask"
        assert "cam1" in item.output_ports[0].endpoint
        assert "mask" in item.output_ports[0].endpoint

    def test_node_without_schemas_backward_compat(self, qtbot):
        """NodeItem без port_schemas: 1 input + 1 output (backward compat)."""
        data = NodeData("node_a", "NodeA")
        item = NodeItem(data)

        assert len(item.input_ports) == 1
        assert len(item.output_ports) == 1

    def test_node_without_schemas_legacy_properties(self, qtbot):
        """NodeItem без port_schemas: input_port и output_port доступны."""
        data = NodeData("node_b", "NodeB")
        item = NodeItem(data)

        assert isinstance(item.input_port, PortItem)
        assert isinstance(item.output_port, PortItem)

    def test_node_with_schemas_backward_compat_first_port(self, qtbot):
        """NodeItem с schemas: input_port/output_port = первый порт."""
        schemas = [
            PortSchema("frame", "input", "image/bgr"),
            PortSchema("mask", "input", "image/gray"),
            PortSchema("result", "output", "image/bgr"),
        ]
        data = NodeData("proc3", "Processor")
        item = NodeItem(data, port_schemas=schemas)

        # Backward compat: первый input/output порт доступен
        assert item.input_port is item.input_ports[0]
        assert item.output_port is item.output_ports[0]

    def test_node_with_scene_correct_ports(self, qtbot):
        """GraphScene.add_node с port_schemas создаёт ноду с нужными портами."""
        schemas = [
            PortSchema("data_in", "input", "dict"),
            PortSchema("data_out", "output", "dict"),
        ]
        scene = GraphScene()
        node = scene.add_node(NodeData("srv", "Service"), port_schemas=schemas)

        assert len(node.input_ports) == 1
        assert len(node.output_ports) == 1

    def test_node_no_schemas_via_scene(self, qtbot):
        """GraphScene.add_node без port_schemas: backward compat."""
        scene = GraphScene()
        node = scene.add_node(NodeData("a", "A", x=100, y=200))

        assert len(node.input_ports) == 1
        assert len(node.output_ports) == 1
        assert node.input_port is not None
        assert node.output_port is not None


# ------------------------------------------------------------------ #
#  PipelineModel.add_wire с type check                               #
# ------------------------------------------------------------------ #

class TestPipelineModelWireTypeCheck:
    """Тесты type-aware валидации wire в PipelineModel."""

    def test_add_wire_compatible_dtypes(self) -> None:
        """Wire с совместимыми dtype добавляется без ошибки."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        old, new = model.add_wire("A.out.0", "B.in.0", "image/bgr", "image/bgr")
        assert len(new["wires"]) == 1

    def test_add_wire_any_dtype_compatible(self) -> None:
        """Wire с any dtype всегда совместим."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        old, new = model.add_wire("A.out.0", "B.in.0", "any", "image/bgr")
        assert len(new["wires"]) == 1

    def test_add_wire_incompatible_dtypes_raises(self) -> None:
        """Wire с несовместимыми dtype вызывает ValueError."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        with pytest.raises(ValueError, match="Несовместимые типы"):
            model.add_wire("A.out.0", "B.in.0", "image/bgr", "image/gray")

    def test_add_wire_wildcard_compatible(self) -> None:
        """Wire с wildcard dtype совместим."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        old, new = model.add_wire("A.out.0", "B.in.0", "image/bgr", "image/*")
        assert len(new["wires"]) == 1

    def test_add_wire_stores_dtype(self) -> None:
        """Wire с dtype хранит информацию о типах в wire dict."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        _, new = model.add_wire("A.out.0", "B.in.0", "image/bgr", "image/bgr")
        wire = new["wires"][0]
        assert wire["src_dtype"] == "image/bgr"
        assert wire["tgt_dtype"] == "image/bgr"

    def test_add_wire_backward_compat_no_dtype(self) -> None:
        """add_wire без dtype работает как раньше (backward compat)."""
        model = PipelineModel()
        model.add_process("A")
        model.add_process("B")
        old, new = model.add_wire("A.out.0", "B.in.0")
        assert len(new["wires"]) == 1
        # src_dtype/tgt_dtype не сохраняются если "any"
        wire = new["wires"][0]
        assert "src_dtype" not in wire
        assert "tgt_dtype" not in wire
