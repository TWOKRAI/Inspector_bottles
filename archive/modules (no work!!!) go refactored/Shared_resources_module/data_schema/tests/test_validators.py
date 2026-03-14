"""
Unit тесты для DataValidator.

Тестирует валидацию данных по Pydantic схемам.
"""

import pytest
from pydantic import BaseModel
from typing import Dict, Any

from ..utils.validators import DataValidator


# ============================================================================
# Тестовые модели
# ============================================================================

class SampleModel(BaseModel):
    """Тестовая модель конфигурации."""

    name: str = "default"
    count: int = 1


class NestedModel(BaseModel):
    """Дополнительная модель для вложенной валидации."""

    value: int = 10


# ============================================================================
# Тесты DataValidator
# ============================================================================

def test_data_validator_variants():
    """Тест различных методов валидации."""
    # Базовая валидация
    valid, instance, err = DataValidator.validate(
        {"name": "v", "count": 2},
        SampleModel,
    )
    assert valid and err is None and instance.count == 2

    # Валидация невалидных данных
    invalid, instance, err = DataValidator.validate(
        {"name": "v", "count": "bad"},
        SampleModel,
    )
    assert not invalid and instance is None and "count" in err

    # Проверка валидности без создания экземпляра
    assert DataValidator.is_valid({"name": "ok", "count": 1}, SampleModel)
    assert not DataValidator.is_valid({"count": "bad"}, SampleModel)

    # Получение ошибок валидации
    errors = DataValidator.get_validation_errors({"count": "bad"}, SampleModel)
    assert errors and errors[0]["loc"][0] == "count"

    # Частичная валидация
    ok_partial, partial, _ = DataValidator.validate_partial(
        {"count": 5},
        SampleModel,
    )
    assert ok_partial and partial.count == 5 and partial.name == "default"

    # Валидация вложенных структур
    nested_data = {"container": {"value": 42}}
    ok_nested, nested_instance, nested_err = DataValidator.validate_nested(
        nested_data,
        NestedModel,
        nested_path="container",
    )
    assert ok_nested and nested_instance.value == 42 and nested_err is None

    # Валидация невалидной вложенной структуры
    bad_nested, _, nested_err = DataValidator.validate_nested(
        {"container": "not-a-dict"},
        NestedModel,
        nested_path="container",
    )
    assert not bad_nested and "не является словарем" in nested_err

