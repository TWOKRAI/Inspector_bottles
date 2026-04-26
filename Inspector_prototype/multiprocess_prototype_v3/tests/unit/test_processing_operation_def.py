"""Unit-тесты для ProcessingOperationDef (Phase 5a + Phase 9 Task 9.2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multiprocess_prototype_v3.registers.processor.catalog.schemas import (
    Port,
    PortDef,
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


# ===========================================================================
# Phase 9 / Task 9.2 — category, multiplicity, display_capable
# ===========================================================================


def test_default_category_is_none():
    """Без указания category → op.category is None."""
    op = ProcessingOperationDef(**_VALID_DATA)
    assert op.category is None


def test_default_multiplicity_is_fixed():
    """Без указания multiplicity → op.multiplicity == 'fixed'."""
    op = ProcessingOperationDef(**_VALID_DATA)
    assert op.multiplicity == "fixed"


def test_default_display_capable_is_false():
    """Без указания display_capable → op.display_capable is False."""
    op = ProcessingOperationDef(**_VALID_DATA)
    assert op.display_capable is False


@pytest.mark.parametrize(
    "category",
    ["Input", "ROI", "Preprocess", "Detect", "Measure", "Logic", "Output"],
)
def test_category_accepts_all_seven_values(category: str):
    """Все 7 значений категории из Literal принимаются без ошибок."""
    op = ProcessingOperationDef(**{**_VALID_DATA, "category": category})
    assert op.category == category


def test_invalid_category_raises():
    """Недопустимое значение category → ValidationError."""
    with pytest.raises(ValidationError):
        ProcessingOperationDef(**{**_VALID_DATA, "category": "UnknownCat"})


def test_multiplicity_dynamic_accepted():
    """Значение multiplicity='dynamic' проходит валидацию."""
    op = ProcessingOperationDef(**{**_VALID_DATA, "multiplicity": "dynamic"})
    assert op.multiplicity == "dynamic"


def test_invalid_multiplicity_raises():
    """Недопустимое значение multiplicity → ValidationError."""
    with pytest.raises(ValidationError):
        ProcessingOperationDef(**{**_VALID_DATA, "multiplicity": "invalid_mult"})


def test_old_yaml_without_new_fields_loads():
    """Словарь без новых полей (category/multiplicity/display_capable) валидируется — поля принимают дефолты."""
    data = {
        "name": "Старая операция",
        "type_key": "legacy_op",
        "params_schema": "registers.processor.processings.legacy.LegacyParams",
        "module_path": "services.processor.operations.legacy_op.LegacyOp",
        "on_error": "skip",
        "description": "Операция без новых полей",
    }
    op = ProcessingOperationDef.model_validate(data)
    assert op.category is None
    assert op.multiplicity == "fixed"
    assert op.display_capable is False


def test_round_trip_with_new_fields():
    """model_dump → model_validate сохраняет значения новых полей."""
    original = ProcessingOperationDef(
        **{
            **_VALID_DATA,
            "category": "Detect",
            "multiplicity": "dynamic",
            "display_capable": True,
        }
    )
    dumped = original.model_dump()
    restored = ProcessingOperationDef.model_validate(dumped)

    assert restored.category == "Detect"
    assert restored.multiplicity == "dynamic"
    assert restored.display_capable is True


def test_portdef_is_alias_of_port():
    """PortDef является алиасом Port — тот же объект."""
    assert PortDef is Port
