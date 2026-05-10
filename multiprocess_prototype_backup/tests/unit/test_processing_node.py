"""Unit-тесты для ProcessingNode, NodeInput, NodeOutput, RegionNode (Phase 5a + Task 9.3)."""

from __future__ import annotations

import uuid

import pytest

from multiprocess_prototype.registers.pipeline.processing_node import (
    NodeInput,
    NodeOutput,
    ProcessingNode,
)
from multiprocess_prototype.registers.pipeline.schemas import RegionNode


# ---------------------------------------------------------------------------
# ProcessingNode
# ---------------------------------------------------------------------------


def test_processing_node_auto_uuid_generated():
    """node_id должен автоматически генерироваться как UUID при создании."""
    node = ProcessingNode(operation_ref="color_detection")
    # Проверяем, что node_id — валидный UUID
    parsed = uuid.UUID(node.node_id)
    assert str(parsed) == node.node_id


def test_processing_node_two_instances_have_different_ids():
    """Два разных экземпляра ProcessingNode должны иметь разные node_id."""
    node1 = ProcessingNode(operation_ref="color_detection")
    node2 = ProcessingNode(operation_ref="color_detection")
    assert node1.node_id != node2.node_id


def test_processing_node_round_trip_serialization():
    """Round-trip: model_dump → model_validate сохраняет все поля."""
    original = ProcessingNode(
        operation_ref="blob_detection",
        params={"threshold": 0.5},
        enabled=False,
        process_id="worker_1",
    )
    dumped = original.model_dump()
    restored = ProcessingNode.model_validate(dumped)

    assert restored.node_id == original.node_id
    assert restored.operation_ref == original.operation_ref
    assert restored.params == original.params
    assert restored.enabled == original.enabled
    assert restored.process_id == original.process_id


def test_processing_node_default_enabled_is_true():
    """Дефолтное значение enabled должно быть True."""
    node = ProcessingNode(operation_ref="color_detection")
    assert node.enabled is True


def test_processing_node_default_process_id():
    """Дефолтное значение process_id должно быть 'processor'."""
    node = ProcessingNode(operation_ref="color_detection")
    assert node.process_id == "processor"


def test_processing_node_default_params_is_empty_dict():
    """Дефолтные params должны быть пустым словарём."""
    node = ProcessingNode(operation_ref="color_detection")
    assert node.params == {}


def test_processing_node_default_inputs_is_empty_list():
    """Дефолтный inputs должен быть пустым списком."""
    node = ProcessingNode(operation_ref="color_detection")
    assert node.inputs == []


# ---------------------------------------------------------------------------
# NodeInput
# ---------------------------------------------------------------------------


def test_node_input_source_required():
    """NodeInput должен принимать source как обязательный аргумент."""
    ni = NodeInput(source="node_abc")
    assert ni.source == "node_abc"


def test_node_input_output_port_default():
    """Дефолтное значение output_port в NodeInput должно быть 'out'."""
    ni = NodeInput(source="frame")
    assert ni.output_port == "out"


def test_node_input_custom_output_port():
    """output_port принимает кастомное значение."""
    ni = NodeInput(source="node_xyz", output_port="mask")
    assert ni.output_port == "mask"


# ---------------------------------------------------------------------------
# RegionNode
# ---------------------------------------------------------------------------


def test_region_node_has_nodes_field():
    """RegionNode должен содержать поле nodes (Phase 5a)."""
    rn = RegionNode()
    assert hasattr(rn, "nodes")
    assert isinstance(rn.nodes, dict)


def test_region_node_has_processing_blocks_field():
    """RegionNode должен содержать поле processing_blocks (backward compat)."""
    rn = RegionNode()
    assert hasattr(rn, "processing_blocks")
    assert isinstance(rn.processing_blocks, dict)


def test_region_node_nodes_can_contain_processing_node():
    """RegionNode.nodes должен принимать ProcessingNode значения."""
    node = ProcessingNode(operation_ref="color_detection")
    rn = RegionNode(nodes={node.node_id: node})
    assert node.node_id in rn.nodes
    assert rn.nodes[node.node_id].operation_ref == "color_detection"


def test_region_node_default_nodes_is_empty():
    """Дефолтный nodes в RegionNode должен быть пустым словарём."""
    rn = RegionNode()
    assert rn.nodes == {}


# ---------------------------------------------------------------------------
# Task 9.3 — NodeOutput + новые поля ProcessingNode
# ---------------------------------------------------------------------------


def test_node_output_default_display_target_is_none():
    """NodeOutput.display_target по умолчанию None."""
    out = NodeOutput(port_name="out")
    assert out.display_target is None


def test_processing_node_default_outputs_is_empty():
    """ProcessingNode.outputs по умолчанию — пустой список."""
    node = ProcessingNode(operation_ref="color_detection")
    assert node.outputs == []


def test_processing_node_default_display_targets_is_empty():
    """ProcessingNode.display_targets по умолчанию — пустой список."""
    node = ProcessingNode(operation_ref="color_detection")
    assert node.display_targets == []


def test_processing_node_default_channel_prefix_is_none():
    """ProcessingNode.channel_prefix по умолчанию None."""
    node = ProcessingNode(operation_ref="color_detection")
    assert node.channel_prefix is None


def test_round_trip_with_new_fields():
    """Round-trip: model_dump → model_validate сохраняет outputs/display_targets/channel_prefix."""
    original = ProcessingNode(
        operation_ref="blob_detection",
        params={"threshold": 0.5},
        outputs=[
            NodeOutput(port_name="out", display_target="window_1"),
            NodeOutput(port_name="mask"),
        ],
        display_targets=["win_main", "win_debug"],
        channel_prefix="blob",
    )
    dumped = original.model_dump()
    restored = ProcessingNode.model_validate(dumped)

    assert len(restored.outputs) == 2
    assert restored.outputs[0].port_name == "out"
    assert restored.outputs[0].display_target == "window_1"
    assert restored.outputs[1].port_name == "mask"
    assert restored.outputs[1].display_target is None
    assert restored.display_targets == ["win_main", "win_debug"]
    assert restored.channel_prefix == "blob"
