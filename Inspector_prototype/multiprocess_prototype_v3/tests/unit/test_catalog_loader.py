"""Unit-тесты для loader.py каталога операций (Phase 5a)."""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_prototype_v3.registers.processor.catalog.loader import (
    load_catalog,
    save_catalog,
)
from multiprocess_prototype_v3.registers.processor.catalog.schemas import (
    ProcessingOperationDef,
)

# Путь к seed-файлу каталога в дереве проекта
_SEED_CATALOG = Path(__file__).resolve().parents[2] / "data" / "processing_catalog.yaml"


def test_load_catalog_seed_returns_two_operations():
    """Загрузка реального seed-файла processing_catalog.yaml → ровно 2 записи."""
    catalog = load_catalog(_SEED_CATALOG)
    assert len(catalog) == 2


def test_load_catalog_seed_contains_color_detection():
    """Seed-каталог должен содержать операцию 'color_detection'."""
    catalog = load_catalog(_SEED_CATALOG)
    assert "color_detection" in catalog


def test_load_catalog_seed_contains_blob_detection():
    """Seed-каталог должен содержать операцию 'blob_detection'."""
    catalog = load_catalog(_SEED_CATALOG)
    assert "blob_detection" in catalog


def test_load_catalog_seed_values_are_processing_operation_def():
    """Значения каталога должны быть экземплярами ProcessingOperationDef."""
    catalog = load_catalog(_SEED_CATALOG)
    for value in catalog.values():
        assert isinstance(value, ProcessingOperationDef)


def test_load_catalog_nonexistent_file_returns_empty_dict():
    """load_catalog с несуществующим файлом возвращает пустой dict (без исключений)."""
    catalog = load_catalog("/nonexistent/path/to/catalog.yaml")
    assert catalog == {}


def test_save_catalog_and_load_round_trip(tmp_path: Path):
    """save_catalog → load_catalog должны давать эквивалентный результат."""
    # Подготовка тестового каталога
    op1 = ProcessingOperationDef(
        name="Операция 1",
        type_key="op_one",
        params_schema="registers.test.Params1",
        module_path="services.test.Op1",
        on_error="skip",
        description="Первая операция",
    )
    op2 = ProcessingOperationDef(
        name="Операция 2",
        type_key="op_two",
        params_schema="registers.test.Params2",
        module_path="services.test.Op2",
        on_error="fail_region",
        description="",
    )
    original_catalog = {"op_one": op1, "op_two": op2}

    # Сохраняем в tmp_path
    yaml_path = tmp_path / "test_catalog.yaml"
    save_catalog(yaml_path, original_catalog)

    # Загружаем обратно
    loaded_catalog = load_catalog(yaml_path)

    assert set(loaded_catalog.keys()) == {"op_one", "op_two"}
    assert loaded_catalog["op_one"].name == "Операция 1"
    assert loaded_catalog["op_one"].on_error == "skip"
    assert loaded_catalog["op_two"].on_error == "fail_region"
    assert loaded_catalog["op_two"].description == ""


def test_save_catalog_creates_parent_dirs(tmp_path: Path):
    """save_catalog должен создавать родительские директории если они не существуют."""
    op = ProcessingOperationDef(
        name="Op",
        type_key="op_x",
        params_schema="registers.Params",
        module_path="services.Op",
    )
    deep_path = tmp_path / "nested" / "dir" / "catalog.yaml"
    save_catalog(deep_path, {"op_x": op})

    # Файл должен существовать
    assert deep_path.exists()


def test_load_catalog_preserves_type_key_as_dict_key(tmp_path: Path):
    """Ключи загруженного каталога соответствуют type_key операций."""
    op = ProcessingOperationDef(
        name="Key Test",
        type_key="my_unique_key",
        params_schema="registers.Params",
        module_path="services.Op",
    )
    path = tmp_path / "catalog.yaml"
    save_catalog(path, {"my_unique_key": op})

    loaded = load_catalog(path)
    assert "my_unique_key" in loaded
    assert loaded["my_unique_key"].type_key == "my_unique_key"


# ===========================================================================
# Phase 9 / Task 9.2 — проверка новых полей в seed-каталоге
# ===========================================================================


def test_seed_catalog_new_fields_loaded_correctly():
    """Загрузка обновлённого processing_catalog.yaml: category и display_capable корректны."""
    catalog = load_catalog(_SEED_CATALOG)

    # color_detection — категория Detect, поддерживает превью
    assert catalog["color_detection"].category == "Detect"
    assert catalog["color_detection"].display_capable is True

    # blob_detection — категория Detect, без превью
    assert catalog["blob_detection"].category == "Detect"
    assert catalog["blob_detection"].display_capable is False
