# -*- coding: utf-8 -*-
"""
Реестр схем данных.

Содержит:
    SchemaRegistry       — реестр Pydantic схем (без Singleton)
    get_default_registry — получить глобальный экземпляр
    register_schema      — декоратор регистрации схем
    discovery            — авто-обнаружение регистров из пакета / файловой системы
    ProcessRegistersRegistry — Singleton реестр RegistersContainer всех процессов

Backward compatibility:
    SchemaManager        — алиас для SchemaRegistry
"""
from .schema_registry import (
    SchemaRegistry,
    SchemaManager,
    register_schema,
    get_default_registry,
)
from .discovery import (
    RegistersScanner,
    discover_registers_from_package,
    register_package_schemas,
    register_package_registers,
    _class_name_to_key,
)
from .process_registry import ProcessRegistersRegistry, RegistersMeta

# Backward compat: старые файлы теперь re-export из discovery
# register_discovery.py и registers_scanner.py остаются как re-export обёртки

__all__ = [
    # Новые имена
    "SchemaRegistry",
    "get_default_registry",
    # Backward compat
    "SchemaManager",
    "register_schema",
    # Discovery
    "RegistersScanner",
    "discover_registers_from_package",
    "register_package_schemas",
    "register_package_registers",
    # Process registry
    "ProcessRegistersRegistry",
    "RegistersMeta",
]
