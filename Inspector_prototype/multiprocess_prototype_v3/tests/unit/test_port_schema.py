"""Unit-тесты для Port, ProcessingOperationDef с портами и совместимости типов (Task 8.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multiprocess_prototype_v3.registers.processor.catalog.port_types import (
    PORT_TYPE_ANY,
    PORT_TYPE_IMAGE,
    PORT_TYPE_MASK,
    are_ports_compatible,
)
from multiprocess_prototype_v3.registers.processor.catalog.schemas import (
    Port,
    ProcessingOperationDef,
)

# ---------------------------------------------------------------------------
# Минимальный валидный набор полей для ProcessingOperationDef
# ---------------------------------------------------------------------------
_VALID_DATA = {
    "name": "Тестовая операция",
    "type_key": "test_op",
    "params_schema": "registers.processor.processings.test.TestParams",
    "module_path": "services.processor.operations.test_op.TestOp",
}


# ===========================================================================
# Тесты модели Port
# ===========================================================================


def test_port_creates_correctly():
    """Port создаётся с нужными полями."""
    p = Port(name="in", data_type=PORT_TYPE_IMAGE)
    assert p.name == "in"
    assert p.data_type == PORT_TYPE_IMAGE
    assert p.optional is False


def test_port_optional_flag():
    """Port с optional=True корректно создаётся."""
    p = Port(name="mask_in", data_type=PORT_TYPE_MASK, optional=True)
    assert p.optional is True


# ===========================================================================
# Тесты default-портов ProcessingOperationDef
# ===========================================================================


def test_default_input_port():
    """Без явных портов → input_ports=[Port('in', 'image')]."""
    op = ProcessingOperationDef(**_VALID_DATA)
    assert len(op.input_ports) == 1
    assert op.input_ports[0].name == "in"
    assert op.input_ports[0].data_type == PORT_TYPE_IMAGE


def test_default_output_port():
    """Без явных портов → output_ports=[Port('out', 'image')]."""
    op = ProcessingOperationDef(**_VALID_DATA)
    assert len(op.output_ports) == 1
    assert op.output_ports[0].name == "out"
    assert op.output_ports[0].data_type == PORT_TYPE_IMAGE


def test_explicit_ports():
    """Явные порты корректно подставляются."""
    op = ProcessingOperationDef(
        **_VALID_DATA,
        input_ports=[
            {"name": "image_in", "data_type": "image"},
            {"name": "mask_in", "data_type": "mask", "optional": True},
        ],
        output_ports=[
            {"name": "image_out", "data_type": "image"},
        ],
    )
    assert len(op.input_ports) == 2
    assert op.input_ports[1].name == "mask_in"
    assert op.input_ports[1].optional is True
    assert len(op.output_ports) == 1


def test_empty_ports_allowed():
    """Операция с пустыми портами (input_ports=[]) допустима."""
    op = ProcessingOperationDef(
        **_VALID_DATA,
        input_ports=[],
        output_ports=[],
    )
    assert op.input_ports == []
    assert op.output_ports == []


# ===========================================================================
# Тест validator: дублирующиеся имена портов
# ===========================================================================


def test_duplicate_input_port_names_raises():
    """Дублирующиеся имена в input_ports → ValidationError."""
    with pytest.raises(ValidationError):
        ProcessingOperationDef(
            **_VALID_DATA,
            input_ports=[
                {"name": "in", "data_type": "image"},
                {"name": "in", "data_type": "mask"},
            ],
        )


def test_duplicate_output_port_names_raises():
    """Дублирующиеся имена в output_ports → ValidationError."""
    with pytest.raises(ValidationError):
        ProcessingOperationDef(
            **_VALID_DATA,
            output_ports=[
                {"name": "out", "data_type": "image"},
                {"name": "out", "data_type": "mask"},
            ],
        )


def test_same_name_in_input_and_output_is_ok():
    """Одинаковые имена в input и output — допустимо (разные списки)."""
    op = ProcessingOperationDef(
        **_VALID_DATA,
        input_ports=[{"name": "data", "data_type": "image"}],
        output_ports=[{"name": "data", "data_type": "image"}],
    )
    assert op.input_ports[0].name == "data"
    assert op.output_ports[0].name == "data"


# ===========================================================================
# Тесты are_ports_compatible
# ===========================================================================


def test_image_to_image_compatible():
    """image → image совместимо."""
    assert are_ports_compatible("image", "image") is True


def test_mask_to_image_incompatible():
    """mask → image несовместимо."""
    assert are_ports_compatible("mask", "image") is False


def test_image_to_any_compatible():
    """image → any совместимо."""
    assert are_ports_compatible("image", "any") is True


def test_any_to_any_compatible():
    """any → any совместимо."""
    assert are_ports_compatible(PORT_TYPE_ANY, PORT_TYPE_ANY) is True


def test_mask_to_mask_compatible():
    """mask → mask совместимо."""
    assert are_ports_compatible("mask", "mask") is True


def test_detections_to_image_incompatible():
    """detections → image несовместимо."""
    assert are_ports_compatible("detections", "image") is False


def test_any_to_image_compatible():
    """any (выход) → image (вход) совместимо."""
    assert are_ports_compatible("any", "image") is True


def test_any_to_mask_compatible():
    """any (выход) → mask (вход) совместимо."""
    assert are_ports_compatible("any", "mask") is True


def test_unknown_output_type_incompatible():
    """Неизвестный output_type → False."""
    assert are_ports_compatible("unknown_type", "image") is False


def test_unknown_input_type_incompatible():
    """Неизвестный input_type → False."""
    assert are_ports_compatible("image", "unknown_type") is False


# ===========================================================================
# Round-trip тест ProcessingOperationDef с портами
# ===========================================================================


def test_round_trip_with_ports():
    """model_dump → model_validate сохраняет порты."""
    op = ProcessingOperationDef(
        **_VALID_DATA,
        input_ports=[{"name": "in", "data_type": "image"}],
        output_ports=[{"name": "out", "data_type": "mask"}],
    )
    dumped = op.model_dump()
    restored = ProcessingOperationDef.model_validate(dumped)

    assert len(restored.input_ports) == 1
    assert restored.input_ports[0].name == "in"
    assert restored.output_ports[0].data_type == "mask"
