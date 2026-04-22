"""Unit-тесты для autofill_inputs (Phase 5a)."""

from __future__ import annotations

import sys
from pathlib import Path

# autofill.py использует короткие импорты:
#   from registers.pipeline.processing_node import NodeInput, ProcessingNode
# Добавляем multiprocess_prototype_v3/ в sys.path
_V3_ROOT = Path(__file__).resolve().parents[2]
_V3_ROOT_STR = str(_V3_ROOT)
if _V3_ROOT_STR not in sys.path:
    sys.path.insert(0, _V3_ROOT_STR)

from multiprocess_prototype_v3.services.processor.chain.autofill import autofill_inputs  # noqa: E402
from multiprocess_prototype_v3.registers.pipeline.processing_node import ProcessingNode  # noqa: E402


# ---------------------------------------------------------------------------
# Вспомогательная функция для создания линейного dict нод (без inputs)
# ---------------------------------------------------------------------------


def _make_nodes(*operation_refs: str) -> dict[str, ProcessingNode]:
    """Создать словарь нод по operation_ref в заданном порядке (inputs не заполнены)."""
    nodes: dict[str, ProcessingNode] = {}
    for op_ref in operation_refs:
        node = ProcessingNode(operation_ref=op_ref)
        nodes[node.node_id] = node
    return nodes


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_autofill_three_nodes_linear_chain():
    """3 ноды → правильная линейная цепочка inputs."""
    nodes = _make_nodes("color_detection", "blob_detection", "postprocess")
    result = autofill_inputs(nodes)

    node_ids = list(result.keys())
    assert len(node_ids) == 3

    # Первая нода — inputs пустой
    first = result[node_ids[0]]
    assert first.inputs == []

    # Вторая нода — берёт вывод первой
    second = result[node_ids[1]]
    assert len(second.inputs) == 1
    assert second.inputs[0].source == node_ids[0]

    # Третья нода — берёт вывод второй
    third = result[node_ids[2]]
    assert len(third.inputs) == 1
    assert third.inputs[0].source == node_ids[1]


def test_autofill_single_node_has_empty_inputs():
    """1 нода → inputs должен быть пустым."""
    nodes = _make_nodes("color_detection")
    result = autofill_inputs(nodes)

    node_id = list(result.keys())[0]
    assert result[node_id].inputs == []


def test_autofill_empty_dict_returns_empty_dict():
    """Пустой dict → пустой dict (без исключений)."""
    result = autofill_inputs({})
    assert result == {}


def test_autofill_does_not_mutate_input():
    """autofill_inputs не мутирует исходный словарь."""
    nodes = _make_nodes("color_detection", "blob_detection")
    node_ids = list(nodes.keys())
    original_inputs = [list(nodes[nid].inputs) for nid in node_ids]

    autofill_inputs(nodes)

    # Исходные inputs остались без изменений
    for nid, original in zip(node_ids, original_inputs):
        assert nodes[nid].inputs == original


def test_autofill_output_port_default_is_out():
    """Заполненный NodeInput должен иметь output_port='out' по умолчанию."""
    nodes = _make_nodes("color_detection", "blob_detection")
    result = autofill_inputs(nodes)

    node_ids = list(result.keys())
    # Вторая нода должна иметь output_port='out'
    second_node = result[node_ids[1]]
    assert second_node.inputs[0].output_port == "out"


def test_autofill_two_nodes_chain():
    """2 ноды → вторая нода указывает на первую."""
    nodes = _make_nodes("color_detection", "blob_detection")
    result = autofill_inputs(nodes)

    node_ids = list(result.keys())
    first_id = node_ids[0]
    second_id = node_ids[1]

    assert result[first_id].inputs == []
    assert len(result[second_id].inputs) == 1
    assert result[second_id].inputs[0].source == first_id
