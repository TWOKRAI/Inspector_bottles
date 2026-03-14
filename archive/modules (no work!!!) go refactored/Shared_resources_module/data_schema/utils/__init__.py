"""
Утилиты для работы с данными.

Содержит конвертеры, валидаторы, хелперы, ссылки и миграцию.
"""

from .converters import DataConverter, FormatType
from .validators import DataValidator
from .helpers import (
    get_nested_value,
    set_nested_value,
    merge_with_defaults,
    extract_fields,
)
from .reference import (
    DataReference,
    is_reference,
    convert_reference_to_data,
    convert_all_references,
)
from .migration import from_dataclass, from_dict, from_json, from_yaml

__all__ = [
    # Конвертеры
    'DataConverter',
    'FormatType',
    
    # Валидаторы
    'DataValidator',
    
    # Хелперы
    'get_nested_value',
    'set_nested_value',
    'merge_with_defaults',
    'extract_fields',
    
    # Ссылки
    'DataReference',
    'is_reference',
    'convert_reference_to_data',
    'convert_all_references',
    
    # Миграция
    'from_dataclass',
    'from_dict',
    'from_json',
    'from_yaml',
]

