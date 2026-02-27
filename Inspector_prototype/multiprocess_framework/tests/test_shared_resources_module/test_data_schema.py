"""
Юнит-тесты для модуля data_schema.

Тестирует публичное API:
- SchemaManager - регистрация и управление схемами
- DataConverter - конвертация между форматами
- DataValidator - валидация данных
- Utils - работа с вложенными структурами
- DataReference - ссылки на ресурсы
"""

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from pydantic import BaseModel, Field

from multiprocess_framework.modules.Shared_resources_module.data_schema.converters import (
    DataConverter,
    FormatType,
)
from multiprocess_framework.modules.Shared_resources_module.data_schema.utils.reference import (
    DataReference,
    convert_all_references,
    is_reference,
)
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaRegistry,
)
from multiprocess_framework.modules.Shared_resources_module.data_schema.utils import (
    get_nested_value,
    set_nested_value,
    merge_with_defaults,
    extract_fields,
    flatten_dict,
    unflatten_dict,
)
from multiprocess_framework.modules.Shared_resources_module.data_schema.validators import (
    DataValidator,
)


# ============================================================================
# Тестовые модели
# ============================================================================

class SampleModel(BaseModel):
    """Тестовая модель конфигурации."""

    name: str = "default"
    count: int = 1
    nested: Dict[str, Any] = Field(default_factory=lambda: {"level": 1})


class NestedModel(BaseModel):
    """Дополнительная модель для вложенной валидации."""

    value: int = 10


# ============================================================================
# Фикстуры
# ============================================================================

@pytest.fixture(autouse=True)
def reset_schema_manager():
    """Сбрасываем одиночку перед каждым тестом, чтобы не загрязнять состояние."""
    registry = SchemaRegistry.get_instance()
    manager.clear_schemas()
    yield manager
    manager.clear_schemas()


# ============================================================================
# Тесты SchemaRegistry
# ============================================================================

def test_schema_registry_basic_flow(reset_schema_registry: SchemaRegistry):
    """Тест базового функционала SchemaRegistry."""
    manager = reset_schema_manager

    # Регистрация схемы
    assert manager.register_schema("Sample", SampleModel)
    assert "Sample" in manager.list_schemas()
    assert manager.has_schema("Sample")
    assert manager.get_schema("Sample") is SampleModel

    # Создание экземпляра с полными данными
    full = manager.create_instance("Sample", {"name": "custom", "count": 5})
    assert full.name == "custom"
    assert full.count == 5

    # Создание экземпляра с частичными данными (дефолты подставляются)
    partial = manager.create_instance("Sample", {"name": "only-name"})
    assert partial.name == "only-name"
    assert partial.count == 1  # дефолт подставлен

    # Получение дефолтных значений
    defaults = manager.get_defaults("Sample")
    assert defaults == SampleModel().model_dump()

    # Валидация валидных данных
    ok, instance, err = manager.validate("Sample", {"name": "x", "count": 2})
    assert ok and err is None and instance.count == 2

    # Валидация невалидных данных
    bad, instance, err = manager.validate("Sample", {"name": "x", "count": "oops"})
    assert not bad and instance is None and "count" in err

    # Удаление схемы
    assert manager.unregister_schema("Sample")
    assert not manager.has_schema("Sample")


def test_schema_registry_thread_safety():
    """Тест потокобезопасности SchemaRegistry (базовый)."""
    import threading

    registry = SchemaRegistry.get_instance()
    manager.clear_schemas()

    def register_schemas():
        for i in range(10):
            class TempModel(BaseModel):
                value: int = i

            manager.register_schema(f"Temp{i}", TempModel)

    threads = [threading.Thread(target=register_schemas) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Проверяем, что все схемы зарегистрированы
    schemas = manager.list_schemas()
    assert len(schemas) == 50  # 10 схем * 5 потоков

    manager.clear_schemas()


# ============================================================================
# Тесты DataConverter
# ============================================================================

def test_data_converter_roundtrips(tmp_path: Path):
    """Тест конвертации между форматами (round-trip)."""
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
    """Тест операций с файлами."""
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


# ============================================================================
# Тесты Utils
# ============================================================================

def test_utils_nested_and_merge():
    """Тест работы с вложенными структурами и объединением."""
    # Установка вложенных значений
    data: Dict[str, Any] = {}
    set_nested_value(data, "database.host", "localhost")
    set_nested_value(data, "database.port", 5432)
    assert data["database"]["host"] == "localhost"
    assert data["database"]["port"] == 5432

    # Получение вложенных значений
    assert get_nested_value(data, "database.port") == 5432
    assert get_nested_value(data, "database.missing", default=10) == 10

    # Объединение с дефолтами
    defaults = {"database": {"host": "127.0.0.1", "timeout": 30}}
    merged = merge_with_defaults(data, defaults)
    assert merged["database"]["host"] == "localhost"  # из data перезаписывает
    assert merged["database"]["timeout"] == 30  # из defaults

    # Извлечение полей
    extracted = extract_fields(
        {"name": "comp", "config": {"log_level": "INFO", "timeout": 5}},
        {"name", "config.log_level"},
        nested=True,
    )
    assert extracted == {"name": "comp", "config": {"log_level": "INFO"}}

    # Flatten/Unflatten
    flat = flatten_dict({"a": {"b": 1, "c": {"d": 2}}})
    assert flat == {"a.b": 1, "a.c.d": 2}
    assert unflatten_dict(flat) == {"a": {"b": 1, "c": {"d": 2}}}


# ============================================================================
# Тесты DataReference
# ============================================================================

def test_data_reference_and_conversion():
    """Тест работы со ссылками на ресурсы."""
    # Хранилище для резолвинга ссылок
    resolved_store: Dict[str, Any] = {
        "queue:1": "qobj",
        "evt:2": {"flag": True}
    }

    def resolver(ref_id: str) -> Any:
        return resolved_store.get(ref_id)

    # Создание и резолвинг ссылки
    ref = DataReference("queue:1", resolver=resolver)
    assert is_reference(ref)
    assert ref.to_dict() == {"_ref": True, "ref_id": "queue:1"}
    assert ref.resolve() == "qobj"

    # Конвертация всех ссылок в структуре данных
    ref_dict = {"_ref": True, "ref_id": "evt:2"}
    data = {
        "queue": ref,
        "evt": ref_dict,
        "plain": 5,
        "items": [ref_dict]
    }
    converted = convert_all_references(data, resolver=resolver)
    assert converted["queue"] == "qobj"
    assert converted["evt"] == {"flag": True}
    assert converted["plain"] == 5  # обычное значение не изменено
    assert converted["items"][0] == {"flag": True}  # ссылка в списке разрешена


def test_data_reference_from_dict():
    """Тест создания ссылки из словаря."""
    def resolver(ref_id: str) -> Any:
        return f"resolved_{ref_id}"

    ref_dict = {"_ref": True, "ref_id": "test:123"}
    ref = DataReference.from_dict(ref_dict, resolver=resolver)
    assert ref.ref_id == "test:123"
    assert ref.resolve() == "resolved_test:123"



