"""
Registry модуль для Shared Resources Module.

Содержит адаптеры и реестры для интеграции с другими модулями системы.
"""

from .data_schema_adapter import DataSchemaAdapter

__all__ = [
    'DataSchemaAdapter',
]

