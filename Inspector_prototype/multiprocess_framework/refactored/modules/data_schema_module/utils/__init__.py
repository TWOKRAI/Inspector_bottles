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
    get_model_schema,
)
from .reference import (
    DataReference,
    is_reference,
    convert_reference_to_data,
    convert_all_references,
)
from .migration import from_dataclass, from_dict, from_json, from_yaml
from .field_schema import FieldSchema
from .registers_io import (
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_yaml,
    registers_from_yaml,
    registers_to_flat_dict,
    registers_from_flat_dict,
)

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
    'get_model_schema',
    
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
    # Схема полей регистров
    'FieldSchema',
    # Ввод/вывод регистров (универсальный)
    'registers_to_dict',
    'registers_from_dict',
    'registers_to_json',
    'registers_from_json',
    'registers_to_yaml',
    'registers_from_yaml',
    'registers_to_flat_dict',
    'registers_from_flat_dict',
]

