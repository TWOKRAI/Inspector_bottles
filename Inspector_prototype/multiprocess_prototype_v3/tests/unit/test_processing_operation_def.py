"""Unit-тесты для ProcessingOperationDef (Phase 5a)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multiprocess_prototype_v3.registers.processor.catalog.schemas import (
    ProcessingOperationDef,
)

# Минимальный валидный набор полей для создания объекта
_VALID_DATA = {
    "name": "Тестовая операция",
    "type_key": "test_op",
    "params_schema": "registers.processor.processings.test.TestParams",
    "module_path": "services.processor.operations.test_op.TestOp",
}


def test_round_trip_model_dump_and_validate():
    """Round-trip: создание → model_dump → model_validate возвращает эквивалентный объект."""
    original = ProcessingOperationDef(**_VALID_DATA)
    dumped = original.model_dump()
    restored = ProcessingOperationDef.model_validate(dumped)

    assert restored.name == original.name
    assert restored.type_key == original.type_key
    assert restored.params_schema == original.params_schema
    assert restored.module_path == original.module_path
    assert restored.on_error == original.on_error
    assert restored.description == original.description


def test_default_on_error_is_skip():
    """Дефолтное значение on_error должно быть 'skip'."""
    op = ProcessingOperationDef(**_VALID_DATA)
    assert op.on_error == "skip"


def test_default_description_is_empty_string():
    """Дефолтное значение description должно быть пустой строкой."""
    op = ProcessingOperationDef(**_VALID_DATA)
    assert op.description == ""


def test_on_error_fail_region_accepted():
    """Значение 'fail_region' должно проходить валидацию."""
    op = ProcessingOperationDef(**{**_VALID_DATA, "on_error": "fail_region"})
    assert op.on_error == "fail_region"


def test_on_error_fail_camera_accepted():
    """Значение 'fail_camera' должно проходить валидацию."""
    op = ProcessingOperationDef(**{**_VALID_DATA, "on_error": "fail_camera"})
    assert op.on_error == "fail_camera"


def test_invalid_on_error_raises_validation_error():
    """Невалидное значение on_error должно бросать ValidationError."""
    with pytest.raises(ValidationError):
        ProcessingOperationDef(**{**_VALID_DATA, "on_error": "invalid_value"})


def test_description_can_be_set():
    """description принимает произвольный текст."""
    op = ProcessingOperationDef(**{**_VALID_DATA, "description": "Описание операции"})
    assert op.description == "Описание операции"


def test_type_key_preserved_in_dump():
    """type_key корректно сохраняется при model_dump."""
    op = ProcessingOperationDef(**_VALID_DATA)
    dumped = op.model_dump()
    assert dumped["type_key"] == "test_op"
