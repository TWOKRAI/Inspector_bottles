"""
Реестр схем данных.

Содержит SchemaRegistry для регистрации и управления Pydantic моделями.
"""

from .schema_registry import SchemaRegistry, register_schema

__all__ = [
    'SchemaRegistry',
    'register_schema',
]


