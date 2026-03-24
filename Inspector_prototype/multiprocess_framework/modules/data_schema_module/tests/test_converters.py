"""
Unit-тесты для DataConverter (utils/converters.py).

Сценарии:
- Round-trip одной Pydantic-модели: dict ↔ model, JSON ↔ model, YAML ↔ model.
- Универсальный convert(from_type, to_type) и работа с файлами (save_to_file, load_from_file).
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field
from typing import Any, Dict

from ..utils.converters import DataConverter, FormatType


# ============================================================================
# Тестовые модели
# ============================================================================

class SampleModel(BaseModel):
    """Тестовая модель конфигурации."""

    name: str = "default"
    count: int = 1
    nested: Dict[str, Any] = Field(default_factory=lambda: {"level": 1})


# ============================================================================
# Тесты DataConverter
# ============================================================================

def test_data_converter_roundtrips(tmp_path: Path):
    """Модель → dict/json/yaml → обратно в модель; универсальный convert(); сохранение/загрузка YAML-файла."""
    model = SampleModel(name="conv", count=3, nested={"level": 2})

    # Model <-> Dict
    dct = DataConverter.model_to_dict(model)
    assert dct["name"] == "conv"
    back_model = DataConverter.dict_to_model(dct, SampleModel)
    assert back_model == model

    # Model <-> JSON
    json_str = DataConverter.model_to_json(model)
    round_trip = DataConverter.json_to_model(json_str, SampleModel)
    assert round_trip == model

    # Model <-> YAML
    yaml_str = DataConverter.model_to_yaml(model)
    yaml_back = DataConverter.yaml_to_model(yaml_str, SampleModel)
    assert yaml_back == model

    # Универсальная конвертация MODEL -> JSON -> MODEL
    converted_json = DataConverter.convert(model, FormatType.MODEL, FormatType.JSON)
    parsed = json.loads(converted_json)
    assert parsed["count"] == 3

    restored = DataConverter.convert(
        converted_json,
        FormatType.JSON,
        FormatType.MODEL,
        model_class=SampleModel,
    )
    assert isinstance(restored, SampleModel)
    assert restored.name == "conv"

    # Сохранение и загрузка из файла
    out_file = tmp_path / "sample.yaml"
    DataConverter.save_to_file(model, out_file, format_type=FormatType.YAML)
    loaded = DataConverter.load_from_file(out_file, model_class=SampleModel)
    assert isinstance(loaded, SampleModel)
    assert loaded.nested == {"level": 2}


def test_data_converter_file_operations(tmp_path: Path):
    """Сохранение модели в JSON и YAML файлы и загрузка обратно в модель."""
    model = SampleModel(name="file_test", count=42)

    # JSON файл
    json_file = tmp_path / "test.json"
    DataConverter.save_to_file(model, json_file)
    loaded_json = DataConverter.load_from_file(json_file, model_class=SampleModel)
    assert loaded_json.name == "file_test"

    # YAML файл
    yaml_file = tmp_path / "test.yaml"
    DataConverter.save_to_file(model, yaml_file, format_type=FormatType.YAML)
    loaded_yaml = DataConverter.load_from_file(yaml_file, model_class=SampleModel)
    assert loaded_yaml.count == 42

