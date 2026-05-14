"""
Unit-тесты для discovery (registry/discovery.py).

Сценарии:
- _class_name_to_key: преобразование имени по суффиксу (Registers/Data) в snake_case.
- discover_registers_from_package: находит классы с заданным суффиксом; несуществующий пакет → {}.
- register_package_registers / register_package_schemas: discovery + регистрация в SchemaManager.
Используется пакет-фикстура tests.fixtures с TestRegisters и TestData.
"""

from pydantic import BaseModel

from ..registry.discovery import (
    discover_registers_from_package,
    register_package_registers,
    register_package_schemas,
    _class_name_to_key,
)
from ..registry.schema_registry import SchemaManager

# Имя пакета-фикстуры (тестовый пакет с TestRegisters и TestData)
FIXTURES_PACKAGE = __name__.rsplit(".", 1)[0] + ".fixtures"


def test_discover_registers_from_package_finds_test_registers():
    """Поиск по пакету возвращает словарь {имя_регистра: класс}; для fixtures — TestRegisters."""
    result = discover_registers_from_package(FIXTURES_PACKAGE)
    # Проверяем, что найден хотя бы один класс *Registers
    assert len(result) > 0
    # Проверяем, что TestRegisters найден (ключ может быть "test" или "test_r" в зависимости от логики преобразования)
    test_registers_class = None
    for key, cls in result.items():
        if cls.__name__ == "TestRegisters":
            test_registers_class = cls
            break
    assert test_registers_class is not None, f"TestRegisters не найден в результате: {result}"
    assert issubclass(test_registers_class, BaseModel)


def test_discover_registers_from_package_unknown_returns_empty():
    """Несуществующий или пустой пакет — возвращается пустой dict (без исключения)."""
    result = discover_registers_from_package("nonexistent.package.xyz")
    assert result == {}


def test_register_package_registers_integrates_with_registry():
    """После вызова register_package_registers все найденные *Registers появляются в SchemaManager."""
    registry = SchemaManager.get_instance()
    registry.clear()
    try:
        ok = register_package_registers(FIXTURES_PACKAGE, schema_registry=registry)
        assert ok is True
        # Находим имя схемы для TestRegisters (может быть "test" или "test_r")
        test_schema_name = None
        for schema_name in registry.list_schemas():
            if registry.get_schema(schema_name).__name__ == "TestRegisters":
                test_schema_name = schema_name
                break
        assert test_schema_name is not None, (
            f"TestRegisters не зарегистрирован. Зарегистрированные: {registry.list_schemas()}"
        )
        assert registry.has_schema(test_schema_name)
        assert registry.get_schema(test_schema_name).__name__ == "TestRegisters"
    finally:
        registry.clear()


def test_register_package_registers_empty_package_returns_false():
    """Если в пакете нет классов *Registers, функция возвращает False (ничего не регистрируется)."""
    registry = SchemaManager.get_instance()
    ok = register_package_registers("nonexistent.package.xyz", schema_registry=registry)
    assert ok is False


# --- Универсальное преобразование имени по суффиксу ---


def test_class_name_to_key_registers():
    """DrawRegisters -> draw, FrameProcessRegisters -> frame_process."""
    assert _class_name_to_key("DrawRegisters", "Registers") == "draw"
    assert _class_name_to_key("FrameProcessRegisters", "Registers") == "frame_process"


def test_class_name_to_key_data():
    """CameraData -> camera, ChainStepData -> chain_step."""
    assert _class_name_to_key("CameraData", "Data") == "camera"
    assert _class_name_to_key("RegionData", "Data") == "region"
    assert _class_name_to_key("ChainStepData", "Data") == "chain_step"


def test_class_name_to_key_wrong_suffix_returns_unchanged():
    """Если суффикс не совпадает, возвращается имя как есть."""
    assert _class_name_to_key("DrawRegisters", "Data") == "DrawRegisters"
    assert _class_name_to_key("CameraData", "Registers") == "CameraData"


# --- Discovery по суффиксу Data ---


def test_discover_registers_from_package_suffix_data():
    """Поиск с suffix='Data' находит классы *Data в пакете-фикстуре."""
    result = discover_registers_from_package(FIXTURES_PACKAGE, suffix="Data")
    assert "test" in result
    assert result["test"].__name__ == "TestData"
    assert issubclass(result["test"], BaseModel)


# --- register_package_schemas (универсальная регистрация по суффиксу) ---


def test_register_package_schemas_with_data_suffix():
    """register_package_schemas(..., suffix='Data') регистрирует *Data в SchemaManager."""
    registry = SchemaManager.get_instance()
    registry.clear()
    try:
        ok = register_package_schemas(FIXTURES_PACKAGE, schema_registry=registry, suffix="Data")
        assert ok is True
        assert registry.has_schema("test")
        assert registry.get_schema("test").__name__ == "TestData"
    finally:
        registry.clear()


def test_register_package_schemas_alias():
    """register_package_registers — алиас register_package_schemas."""
    assert register_package_registers is register_package_schemas
