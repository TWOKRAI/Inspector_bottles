"""
Реестр схем данных.

Содержит:
    SchemaManager        — регистрация и получение Pydantic схем
    register_discovery   — авто-обнаружение регистров из пакета
    RegistersScanner     — сканирование директории по .py файлам
    ProcessRegistersRegistry — Singleton реестр RegistersContainer всех процессов
    RegistersMeta        — метаданные процесса для ProcessRegistersRegistry
"""

from .schema_registry import SchemaManager, register_schema
from .register_discovery import (
    discover_registers_from_package,
    register_package_registers,
    register_package_schemas,
)
from .registers_scanner import RegistersScanner
from .process_registry import ProcessRegistersRegistry, RegistersMeta

__all__ = [
    'SchemaManager',
    'register_schema',
    'discover_registers_from_package',
    'register_package_registers',
    'register_package_schemas',
    'RegistersScanner',
    'ProcessRegistersRegistry',
    'RegistersMeta',
]


