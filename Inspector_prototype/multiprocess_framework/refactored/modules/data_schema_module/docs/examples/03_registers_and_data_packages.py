"""
Пример: discovery и регистрация по пакетам (Registers / Data).

Показывает универсальный механизм фреймворка без привязки к конкретному приложению.
Используется тестовый пакет data_schema_module.tests.fixtures (TestRegisters, TestData).
В реальном приложении подставляете свои пакеты, например App.Registers.models.field_registers.
"""

from ..registry.register_discovery import (
    discover_registers_from_package,
    register_package_schemas,
)
from ..registry.schema_registry import SchemaManager
from ..utils.registers_container import RegistersContainer

# Пакет-фикстура (в приложении: "App.Registers.models.field_registers" и "...field_data")
FIXTURES_PACKAGE = "data_schema_module.tests.fixtures"


def main():
    # 1) Discovery по суффиксу Registers
    registers_map = discover_registers_from_package(FIXTURES_PACKAGE, suffix="Registers")
    print("Registers:", list(registers_map.keys()), list(registers_map.values()))

    # 2) Контейнер регистров
    container = RegistersContainer(registers_map)
    print("register_names:", container.register_names())
    r = container.get_register("test")
    print("get_register('test'):", r, "value=", getattr(r, "value", None))

    # 3) Discovery по суффиксу Data
    data_map = discover_registers_from_package(FIXTURES_PACKAGE, suffix="Data")
    print("Data models:", list(data_map.keys()), [c.__name__ for c in data_map.values()])

    # 4) Регистрация дата-схем в SchemaManager
    registry = SchemaManager.get_instance()
    registry.clear()
    try:
        ok = register_package_schemas(FIXTURES_PACKAGE, schema_registry=registry, suffix="Data")
        print("register_package_schemas(..., suffix='Data'):", ok)
        print("SchemaManager has 'test':", registry.has_schema("test"))
    finally:
        registry.clear()


if __name__ == "__main__":
    main()
