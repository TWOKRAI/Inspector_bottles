"""
Реестр схем данных.

Содержит SchemaManager для регистрации и управления Pydantic моделями,
и register_discovery для автообнаружения классов регистров в пакете.
"""

from .schema_registry import SchemaManager, register_schema
from .register_discovery import (
    discover_registers_from_package,
    register_package_registers,
    register_package_schemas,
)

__all__ = [
    'SchemaManager',
    'register_schema',
    'discover_registers_from_package',
    'register_package_registers',
    'register_package_schemas',
]


