"""
Unit-тесты для FieldSchema (utils/field_schema.py).

Сценарии:
- Инициализация от словаря и вызов экземпляра как поля: default + description + overrides → Field.
- Рекурсивное слияние словарей (deep_merge): base + overrides, приоритет у overrides.
- Использование поля, созданного через FieldSchema, в Pydantic-модели (валидация и дефолты).
"""

from typing import Any, Dict

import pytest
from pydantic import BaseModel

from ..utils.field_schema import FieldSchema


def test_field_schema_init_and_call():
    """Экземпляр создаётся от базовой схемы; вызов (default, description, **overrides) возвращает Field с слитым json_schema_extra."""
    schema: Dict[str, Any] = {"min": 0, "max": 100, "unit": ""}
    fs = FieldSchema(schema)
    f = fs(1.4, description="Test field", min=0.1, max=20.0)
    assert f.default == 1.4
    assert f.description == "Test field"
    assert f.json_schema_extra["min"] == 0.1
    assert f.json_schema_extra["max"] == 20.0
    assert f.json_schema_extra["unit"] == ""


def test_field_schema_deep_merge_nested():
    """Статический deep_merge: вложенные ключи мержатся рекурсивно, значения из overrides перезаписывают base."""
    base = {"a": 1, "nested": {"x": 10, "y": 20}}
    overrides = {"nested": {"x": 99}, "b": 2}
    result = FieldSchema.deep_merge(base, overrides)
    assert result["a"] == 1
    assert result["b"] == 2
    assert result["nested"]["x"] == 99
    assert result["nested"]["y"] == 20


def test_field_schema_used_in_model():
    """Поле из FieldSchema подставляется в модель; дефолт и переопределение при создании экземпляра работают."""
    schema: Dict[str, Any] = {"min": 0, "max": 10}
    fs = FieldSchema(schema)
    value_field = fs(5, description="Value", min=0, max=10)

    class SampleModel(BaseModel):
        value: int = value_field

    m = SampleModel()
    assert m.value == 5
    m2 = SampleModel(value=7)
    assert m2.value == 7
