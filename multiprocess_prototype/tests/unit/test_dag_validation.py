"""Unit-тесты для DAG-валидации портов в GraphRunnableBuilder (Task 8.2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Добавляем multiprocess_prototype/ в sys.path для коротких импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
_V3_ROOT_STR = str(_V3_ROOT)
if _V3_ROOT_STR not in sys.path:
    sys.path.insert(0, _V3_ROOT_STR)

from multiprocess_prototype.registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from multiprocess_prototype.registers.processor.catalog.port_types import (  # noqa: E402
    PORT_TYPE_DETECTIONS,
    PORT_TYPE_IMAGE,
    PORT_TYPE_MASK,
)
from multiprocess_prototype.registers.processor.catalog.schemas import (  # noqa: E402
    Port,
    ProcessingOperationDef,
)
from multiprocess_prototype.services.processor.chain.builder import (  # noqa: E402
    GraphRunnableBuilder,
    _validate_ports,
)

# ---------------------------------------------------------------------------
# Фикстуры — определения операций с портами
# ---------------------------------------------------------------------------


def _make_op_def(
    type_key: str,
    input_ports: list[Port] | None = None,
    output_ports: list[Port] | None = None,
) -> ProcessingOperationDef:
    """Создать определение операции с указанными портами."""
    kwargs: dict = {
        "name": f"Операция {type_key}",
        "type_key": type_key,
        "params_schema": f"registers.processor.processings.{type_key}.Params",
        "module_path": f"services.processor.operations.{type_key}_op.Op",
        "on_error": "skip",
    }
    if input_ports is not None:
        kwargs["input_ports"] = input_ports
    if output_ports is not None:
        kwargs["output_ports"] = output_ports
    return ProcessingOperationDef(**kwargs)


@pytest.fixture
def image_op_def() -> ProcessingOperationDef:
    """Операция image→image (default порты)."""
    return _make_op_def("image_op")


@pytest.fixture
def mask_producer_def() -> ProcessingOperationDef:
    """Операция: вход image, выход mask."""
    return _make_op_def(
        "mask_producer",
        input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
        output_ports=[Port(name="out", data_type=PORT_TYPE_MASK)],
    )


@pytest.fixture
def mask_consumer_def() -> ProcessingOperationDef:
    """Операция: вход mask, выход image."""
    return _make_op_def(
        "mask_consumer",
        input_ports=[Port(name="in", data_type=PORT_TYPE_MASK)],
        output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
    )


@pytest.fixture
def detection_consumer_def() -> ProcessingOperationDef:
    """Операция: вход detections."""
    return _make_op_def(
        "detection_consumer",
        input_ports=[Port(name="in", data_type=PORT_TYPE_DETECTIONS)],
        output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
    )


@pytest.fixture
def merge_op_def() -> ProcessingOperationDef:
    """Операция с двумя входами: image + mask → image."""
    return _make_op_def(
        "merge_op",
        input_ports=[
            Port(name="image_in", data_type=PORT_TYPE_IMAGE),
            Port(name="mask_in", data_type=PORT_TYPE_MASK),
        ],
        output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
    )


# ---------------------------------------------------------------------------
# Тесты валидации портов
# ---------------------------------------------------------------------------


class TestPortValidation:
    """Тесты для _validate_ports."""

    def test_compatible_ports_no_error(self, image_op_def):
        """Совместимые порты (image→image) — нет ошибки."""
        node_a = ProcessingNode(node_id="a", operation_ref="image_op")
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        nodes = {"a": node_a, "b": node_b}
        catalog = {"image_op": image_op_def}

        # Не должно бросить исключение
        _validate_ports(nodes, catalog)

    def test_incompatible_port_types_raises(self, image_op_def, detection_consumer_def):
        """image→detections — несовместимо → ValueError."""
        node_a = ProcessingNode(node_id="a", operation_ref="image_op")
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="detection_consumer",
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        nodes = {"a": node_a, "b": node_b}
        catalog = {
            "image_op": image_op_def,
            "detection_consumer": detection_consumer_def,
        }

        with pytest.raises(ValueError, match="Несовместимые типы портов"):
            _validate_ports(nodes, catalog)

    def test_nonexistent_output_port_raises(self, image_op_def):
        """Ссылка на несуществующий выходной порт → ValueError."""
        node_a = ProcessingNode(node_id="a", operation_ref="image_op")
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a", output_port="nonexistent", input_port="in")],
        )
        nodes = {"a": node_a, "b": node_b}
        catalog = {"image_op": image_op_def}

        with pytest.raises(ValueError, match="выходной порт.*nonexistent"):
            _validate_ports(nodes, catalog)

    def test_nonexistent_input_port_raises(self, image_op_def):
        """Ссылка на несуществующий входной порт → ValueError."""
        node_a = ProcessingNode(node_id="a", operation_ref="image_op")
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a", output_port="out", input_port="nonexistent")],
        )
        nodes = {"a": node_a, "b": node_b}
        catalog = {"image_op": image_op_def}

        with pytest.raises(ValueError, match="входного порта.*nonexistent"):
            _validate_ports(nodes, catalog)

    def test_mask_to_mask_compatible(self, mask_producer_def, mask_consumer_def):
        """mask→mask — совместимо."""
        node_a = ProcessingNode(node_id="a", operation_ref="mask_producer")
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="mask_consumer",
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        nodes = {"a": node_a, "b": node_b}
        catalog = {
            "mask_producer": mask_producer_def,
            "mask_consumer": mask_consumer_def,
        }

        # Не должно бросить исключение
        _validate_ports(nodes, catalog)

    def test_merge_two_inputs_validated(self, image_op_def, mask_producer_def, merge_op_def):
        """Merge нода с двумя входами — валидация обоих портов."""
        node_img = ProcessingNode(node_id="img", operation_ref="image_op")
        node_mask = ProcessingNode(
            node_id="mask",
            operation_ref="mask_producer",
            inputs=[NodeInput(source="img", output_port="out", input_port="in")],
        )
        node_merge = ProcessingNode(
            node_id="merge",
            operation_ref="merge_op",
            inputs=[
                NodeInput(
                    source="img",
                    output_port="out",
                    input_port="image_in",
                ),
                NodeInput(
                    source="mask",
                    output_port="out",
                    input_port="mask_in",
                ),
            ],
        )
        nodes = {
            "img": node_img,
            "mask": node_mask,
            "merge": node_merge,
        }
        catalog = {
            "image_op": image_op_def,
            "mask_producer": mask_producer_def,
            "merge_op": merge_op_def,
        }

        # Не должно бросить исключение
        _validate_ports(nodes, catalog)

    def test_frame_source_skipped(self, image_op_def):
        """Источник 'frame' не валидируется — это виртуальный вход."""
        node = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame", output_port="out", input_port="in")],
        )
        nodes = {"a": node}
        catalog = {"image_op": image_op_def}

        # Не должно бросить исключение
        _validate_ports(nodes, catalog)


class TestCycleDetection:
    """Тесты для обнаружения циклов (уже работает, проверяем)."""

    def test_cycle_raises_value_error(self, image_op_def):
        """Граф A→B→A → ValueError."""
        node_a = ProcessingNode(node_id="a", operation_ref="image_op")
        node_b = ProcessingNode(node_id="b", operation_ref="image_op")
        node_a = node_a.model_copy(update={"inputs": [NodeInput(source="b")]})
        node_b = node_b.model_copy(update={"inputs": [NodeInput(source="a")]})
        nodes = {"a": node_a, "b": node_b}
        catalog = {"image_op": image_op_def}

        with pytest.raises(ValueError, match="цикл|cycle"):
            GraphRunnableBuilder.build(nodes, catalog)


class TestNodeInputPort:
    """Тесты для нового поля NodeInput.input_port."""

    def test_default_input_port_is_in(self):
        """По умолчанию input_port == 'in' (обратная совместимость)."""
        inp = NodeInput(source="some_node")
        assert inp.input_port == "in"

    def test_custom_input_port(self):
        """Можно задать произвольный input_port."""
        inp = NodeInput(source="some_node", input_port="mask_in")
        assert inp.input_port == "mask_in"

    def test_serialization_roundtrip(self):
        """NodeInput с input_port сериализуется/десериализуется корректно."""
        inp = NodeInput(
            source="node_a",
            output_port="mask_out",
            input_port="mask_in",
        )
        data = inp.model_dump()
        restored = NodeInput.model_validate(data)
        assert restored.source == "node_a"
        assert restored.output_port == "mask_out"
        assert restored.input_port == "mask_in"
