"""
Утилиты для работы с данными.

Предоставляет вспомогательные функции для:
- Работы с вложенными структурами (точечная нотация)
- Объединения данных с дефолтными значениями
- Извлечения полей из моделей
"""

from typing import Any, Dict, Optional, List, Set
from pydantic import BaseModel
from .reference import (
    DataReference,
    is_reference as _is_reference,
    convert_reference_to_data as _convert_reference_to_data,
    convert_all_references as _convert_all_references,
)


def get_nested_value(
    data: Dict[str, Any],
    key: str,
    default: Any = None
) -> Any:
    """
    Получить значение из вложенного словаря по точечной нотации.
    
    Args:
        data: Словарь данных
        key: Ключ (поддерживает точечную нотацию, например 'database.host')
        default: Значение по умолчанию
        
    Returns:
        Значение или default
        
    Example:
        data = {
            "database": {
                "host": "localhost",
                "port": 5432
            }
        }
        
        host = get_nested_value(data, "database.host")  # "localhost"
        timeout = get_nested_value(data, "database.timeout", 30)  # 30
    """
    if '.' not in key:
        return data.get(key, default)
    
    keys = key.split('.')
    value = data
    
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
            if value is None:
                return default
        else:
            return default
    
    return value if value is not None else default


def set_nested_value(
    data: Dict[str, Any],
    key: str,
    value: Any
) -> None:
    """
    Установить значение во вложенном словаре по точечной нотации.
    
    Args:
        data: Словарь данных
        key: Ключ (поддерживает точечную нотацию)
        value: Значение для установки
        
    Example:
        data = {}
        set_nested_value(data, "database.host", "localhost")
        set_nested_value(data, "database.port", 5432)
        
        # Результат:
        # {
        #     "database": {
        #         "host": "localhost",
        #         "port": 5432
        #     }
        # }
    """
    if '.' not in key:
        data[key] = value
        return
    
    keys = key.split('.')
    current = data
    
    for k in keys[:-1]:
        if k not in current:
            current[k] = {}
        elif not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    
    current[keys[-1]] = value


def merge_with_defaults(
    data: Dict[str, Any],
    defaults: Dict[str, Any],
    deep: bool = True
) -> Dict[str, Any]:
    """
    Объединить данные с дефолтными значениями.
    
    Значения из data перезаписывают значения из defaults.
    Вложенные словари объединяются рекурсивно если deep=True.
    
    Args:
        data: Данные для объединения
        defaults: Дефолтные значения
        deep: Рекурсивное объединение вложенных словарей
        
    Returns:
        Объединенный словарь
        
    Example:
        defaults = {
            "log_level": "INFO",
            "config": {
                "timeout": 30,
                "retries": 3
            }
        }
        
        data = {
            "log_level": "DEBUG",  # Перезапишет дефолт
            "config": {
                "timeout": 60  # Перезапишет дефолт, retries останется из defaults
            }
        }
        
        result = merge_with_defaults(data, defaults)
        # {
        #     "log_level": "DEBUG",
        #     "config": {
        #         "timeout": 60,
        #         "retries": 3
        #     }
        # }
    """
    if not deep:
        result = defaults.copy()
        result.update(data)
        return result
    
    result = defaults.copy()
    
    for key, value in data.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_with_defaults(value, result[key], deep=True)
        else:
            result[key] = value
    
    return result


def extract_fields(
    data: Dict[str, Any],
    fields: Set[str],
    nested: bool = False
) -> Dict[str, Any]:
    """
    Извлечь указанные поля из данных.
    
    Args:
        data: Исходные данные
        fields: Множество имен полей для извлечения
        nested: Поддерживать точечную нотацию для вложенных полей
        
    Returns:
        Словарь с извлеченными полями
        
    Example:
        data = {
            "name": "test",
            "config": {
                "log_level": "INFO",
                "timeout": 30
            },
            "other": "value"
        }
        
        # Извлечь только name и log_level из config
        result = extract_fields(
            data,
            {"name", "config.log_level"},
            nested=True
        )
        # {
        #     "name": "test",
        #     "config": {
        #         "log_level": "INFO"
        #     }
        # }
    """
    if not nested:
        return {k: v for k, v in data.items() if k in fields}
    
    result = {}
    
    for field_path in fields:
        if '.' in field_path:
            # Вложенное поле
            parts = field_path.split('.')
            value = get_nested_value(data, field_path)
            if value is not None:
                set_nested_value(result, field_path, value)
        else:
            # Простое поле
            if field_path in data:
                result[field_path] = data[field_path]
    
    return result


def get_model_fields(model_class: type[BaseModel]) -> List[str]:
    """
    Получить список полей Pydantic модели.
    
    Args:
        model_class: Класс Pydantic модели
        
    Returns:
        Список имен полей
    """
    return list(model_class.model_fields.keys())


def get_model_defaults(model_class: type[BaseModel]) -> Dict[str, Any]:
    """
    Получить дефолтные значения полей Pydantic модели.
    
    Args:
        model_class: Класс Pydantic модели
        
    Returns:
        Словарь с дефолтными значениями
    """
    instance = model_class()
    return instance.model_dump(exclude_unset=True)


def get_model_schema(model_class: type[BaseModel]) -> Dict[str, Any]:
    """
    Построить словарь-схему по Pydantic модели.

    Возвращает структуру:
        {
            "field_name": {
                "type": str(...),
                "default": <значение по умолчанию>,
                "description": "...",
                "json_schema_extra": {...},
            },
            ...
        }

    Это даёт «вид», похожий на data_schemas.py, но без ручного дублирования:
    источник истины — сама модель (model_fields + json_schema_extra).
    """
    fields = getattr(model_class, "model_fields", {})
    defaults = get_model_defaults(model_class)

    schema: Dict[str, Any] = {}
    for name, field in fields.items():
        annotation = getattr(field, "annotation", Any)
        type_repr = getattr(annotation, "__name__", None) or str(annotation)
        default_value = defaults.get(name, None)
        description = getattr(field, "description", None)
        extra = getattr(field, "json_schema_extra", None) or {}

        schema[name] = {
            "type": type_repr,
            "default": default_value,
            "description": description,
            "json_schema_extra": extra,
        }

    return schema


def flatten_dict(
    data: Dict[str, Any],
    separator: str = '.',
    prefix: str = ''
) -> Dict[str, Any]:
    """
    Преобразовать вложенный словарь в плоский с точечной нотацией.
    
    Args:
        data: Вложенный словарь
        separator: Разделитель для ключей
        prefix: Префикс для ключей (для рекурсии)
        
    Returns:
        Плоский словарь
        
    Example:
        data = {
            "database": {
                "host": "localhost",
                "port": 5432
            }
        }
        
        result = flatten_dict(data)
        # {
        #     "database.host": "localhost",
        #     "database.port": 5432
        # }
    """
    result = {}
    
    for key, value in data.items():
        new_key = f"{prefix}{separator}{key}" if prefix else key
        
        if isinstance(value, dict):
            result.update(flatten_dict(value, separator, new_key))
        else:
            result[new_key] = value
    
    return result


def unflatten_dict(
    data: Dict[str, Any],
    separator: str = '.'
) -> Dict[str, Any]:
    """
    Преобразовать плоский словарь с точечной нотацией во вложенный.
    
    Args:
        data: Плоский словарь
        separator: Разделитель в ключах
        
    Returns:
        Вложенный словарь
        
    Example:
        data = {
            "database.host": "localhost",
            "database.port": 5432
        }
        
        result = unflatten_dict(data)
        # {
        #     "database": {
        #         "host": "localhost",
        #         "port": 5432
        #     }
        # }
    """
    result = {}
    
    for key, value in data.items():
        set_nested_value(result, key, value)
    
    return result


# -----------------------------------------------------------------------------
# Работа со ссылками (DataReference)
# -----------------------------------------------------------------------------

def is_reference(value: Any) -> bool:
    """Проверить, является ли значение ссылкой (DataReference или словарь со _ref)."""
    return _is_reference(value)


def convert_reference_to_data(ref: Any, resolver: Optional[Any] = None) -> Optional[Any]:
    """Конвертировать ссылку в данные."""
    return _convert_reference_to_data(ref, resolver)


def convert_all_references(
    data: Any,
    resolver: Optional[Any] = None,
    max_depth: int = 10,
    current_depth: int = 0
) -> Any:
    """Рекурсивно конвертировать все ссылки в структуре данных."""
    return _convert_all_references(data, resolver, max_depth, current_depth)

