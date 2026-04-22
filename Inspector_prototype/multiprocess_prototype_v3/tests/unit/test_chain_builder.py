"""Unit-тесты для GraphRunnableBuilder (Phase 5a)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# builder.py и runnable.py используют короткие импорты:
#   from registers.pipeline.processing_node import ...
#   from services.processor.operations.loader import ...
# Добавляем multiprocess_prototype_v3/ в sys.path чтобы они резолвились
_V3_ROOT = Path(__file__).resolve().parents[2]
_V3_ROOT_STR = str(_V3_ROOT)
if _V3_ROOT_STR not in sys.path:
    sys.path.insert(0, _V3_ROOT_STR)

from multiprocess_prototype_v3.services.processor.chain.builder import (  # noqa: E402
    GraphRunnableBuilder,
)
from multiprocess_prototype_v3.services.processor.chain.runnable import ChainRunnable  # noqa: E402
from multiprocess_prototype_v3.registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from multiprocess_prototype_v3.registers.processor.catalog.schemas import (  # noqa: E402
    ProcessingOperationDef,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def color_op_def() -> ProcessingOperationDef:
    """Описание операции цветовой детекции из реального каталога."""
    return ProcessingOperationDef(
        name="Цветовая детекция",
        type_key="color_detection",
        params_schema="registers.processor.processings.color_detection.ColorDetectionParams",
        module_path="services.processor.operations.color_detection_op.ColorDetectionOp",
        on_error="skip",
    )


@pytest.fixture
def blob_op_def() -> ProcessingOperationDef:
    """Описание операции blob-детекции из реального каталога."""
    return ProcessingOperationDef(
        name="Детекция блобов",
        type_key="blob_detection",
        params_schema="registers.processor.processings.blob_detection.BlobDetectionParams",
        module_path="services.processor.operations.blob_detection_op.BlobDetectionOp",
        on_error="skip",
    )


@pytest.fixture
def two_node_catalog(color_op_def, blob_op_def) -> dict[str, ProcessingOperationDef]:
    """Каталог с двумя операциями: color_detection + blob_detection."""
    return {
        "color_detection": color_op_def,
        "blob_detection": blob_op_def,
    }


def _make_linear_nodes(*operation_refs: str) -> dict[str, ProcessingNode]:
    """Вспомогательная функция: создать линейную цепочку нод с заполненными inputs."""
    nodes: dict[str, ProcessingNode] = {}
    prev_id: str | None = None

    for op_ref in operation_refs:
        node = ProcessingNode(operation_ref=op_ref)
        if prev_id is not None:
            # Линейная зависимость: каждый следующий берёт вывод предыдущего
            node = node.model_copy(update={"inputs": [NodeInput(source=prev_id)]})
        nodes[node.node_id] = node
        prev_id = node.node_id

    return nodes


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_build_two_nodes_returns_chain_with_two_steps(two_node_catalog):
    """Две активные ноды (color + blob) → chain с 2 шагами."""
    nodes = _make_linear_nodes("color_detection", "blob_detection")
    chain = GraphRunnableBuilder.build(nodes, two_node_catalog)

    assert isinstance(chain, ChainRunnable)
    assert len(chain.steps) == 2


def test_build_disabled_node_is_skipped(two_node_catalog):
    """Нода с enabled=False пропускается — chain содержит только активную ноду."""
    # Создаём одну активную и одну disabled ноду
    active_node = ProcessingNode(operation_ref="color_detection")
    disabled_node = ProcessingNode(
        operation_ref="blob_detection",
        enabled=False,
        inputs=[NodeInput(source=active_node.node_id)],
    )
    nodes = {
        active_node.node_id: active_node,
        disabled_node.node_id: disabled_node,
    }

    chain = GraphRunnableBuilder.build(nodes, two_node_catalog)

    # Только 1 шаг — disabled нода пропущена
    assert len(chain.steps) == 1
    assert chain.steps[0].node.operation_ref == "color_detection"


def test_build_operation_ref_not_in_catalog_raises_key_error():
    """operation_ref отсутствующий в каталоге → KeyError."""
    node = ProcessingNode(operation_ref="nonexistent_op")
    nodes = {node.node_id: node}
    empty_catalog: dict[str, ProcessingOperationDef] = {}

    with pytest.raises(KeyError, match="nonexistent_op"):
        GraphRunnableBuilder.build(nodes, empty_catalog)


def test_build_empty_nodes_returns_empty_chain(two_node_catalog):
    """Пустой dict nodes → пустая цепочка без шагов."""
    chain = GraphRunnableBuilder.build({}, two_node_catalog)

    assert isinstance(chain, ChainRunnable)
    assert len(chain.steps) == 0


def test_build_cycle_raises_value_error(two_node_catalog):
    """Граф с циклом (A → B → A) → ValueError с упоминанием цикла."""
    node_a = ProcessingNode(operation_ref="color_detection")
    node_b = ProcessingNode(operation_ref="blob_detection")

    # Создаём цикл: A зависит от B, B зависит от A
    node_a = node_a.model_copy(update={"inputs": [NodeInput(source=node_b.node_id)]})
    node_b = node_b.model_copy(update={"inputs": [NodeInput(source=node_a.node_id)]})

    nodes = {
        node_a.node_id: node_a,
        node_b.node_id: node_b,
    }

    with pytest.raises(ValueError, match="цикл|cycle"):
        GraphRunnableBuilder.build(nodes, two_node_catalog)


def test_build_single_node_chain(color_op_def):
    """Одна активная нода → chain с 1 шагом."""
    node = ProcessingNode(operation_ref="color_detection")
    nodes = {node.node_id: node}
    catalog = {"color_detection": color_op_def}

    chain = GraphRunnableBuilder.build(nodes, catalog)

    assert len(chain.steps) == 1
    assert chain.steps[0].node.operation_ref == "color_detection"
