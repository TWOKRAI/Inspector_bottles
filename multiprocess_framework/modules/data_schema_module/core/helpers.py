# -*- coding: utf-8 -*-
"""
Утилиты для работы с данными.

Предоставляет вспомогательные функции для:
- Работы с вложенными структурами (точечная нотация)
- Объединения данных с дефолтными значениями
- Извлечения полей из моделей
"""

import copy
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel

from .reference import (
    is_reference as _is_reference,
    convert_reference_to_data as _convert_reference_to_data,
    convert_all_references as _convert_all_references,
)


def get_nested_value(
    data: Dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """
    Получить значение из вложенного словаря по точечной нотации.

    Example:
        data = {"database": {"host": "localhost", "port": 5432}}
        host = get_nested_value(data, "database.host")  # "localhost"
        timeout = get_nested_value(data, "database.timeout", 30)  # 30
    """
    if "." not in key:
        return data.get(key, default)

    keys = key.split(".")
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
    value: Any,
) -> None:
    """
    Установить значение во вложенном словаре по точечной нотации.

    Example:
        data = {}
        set_nested_value(data, "database.host", "localhost")
        # data == {"database": {"host": "localhost"}}
    """
    if "." not in key:
        data[key] = value
        return

    keys = key.split(".")
    current = data

    for k in keys[:-1]:
        if k not in current:
            current[k] = {}
        elif not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]

    current[keys[-1]] = value


def deep_merge(
    base: Dict[str, Any],
    overlay: Optional[Dict[str, Any]],
    *,
    copy_base: bool = True,
    list_strategy: str = "replace",
) -> Dict[str, Any]:
    """
    Канонический рекурсивный merge *overlay* поверх *base* (дубль D3, C5).

    Единая реализация deep-merge словарей для всего проекта. Тонкие делегаты:
    ``merge_with_defaults`` (ниже), ``config_module.tools.deep_merge``,
    ``multiprocess_prototype...schemas._deep_merge``.

    Overlay побеждает при конфликте. В отличие от исторических копий делает
    полную изоляцию (``deepcopy`` base и overlay-значений) — результат не
    разделяет вложенных ссылок с аргументами.

    Args:
        base: Базовый dict (дефолты).
        overlay: Dict для наложения. ``None``/пустой → возвращает копию base.
        copy_base: ``True`` — deepcopy base (безопасно). ``False`` — мутация на месте.
        list_strategy: Стратегия для list-значений:
            - ``"replace"`` — overlay полностью заменяет base (по умолчанию)
            - ``"append"`` — overlay элементы добавляются к base

    Returns:
        Объединённый dict.
    """
    if copy_base:
        result = copy.deepcopy(base)
    else:
        result = base

    if not overlay:
        return result

    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Рекурсия для вложенных dict'ов — base уже скопирован сверху.
            result[key] = deep_merge(
                result[key],
                value,
                copy_base=False,
                list_strategy=list_strategy,
            )
        elif list_strategy == "append" and key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)

    return result


def merge_with_defaults(
    data: Dict[str, Any],
    defaults: Dict[str, Any],
    deep: bool = True,
) -> Dict[str, Any]:
    """
    Объединить данные с дефолтными значениями.

    Значения из data перезаписывают значения из defaults.
    Вложенные словари объединяются рекурсивно если deep=True.

    Тонкий делегат канонического :func:`deep_merge` (дубль D3, C5). При
    ``deep=True`` эквивалентен ``deep_merge(defaults, data)`` — data побеждает.
    Историческая реализация делала shallow-copy defaults; канон делает deepcopy,
    поэтому результат больше не разделяет вложенных ссылок с аргументами
    (наблюдаемый ``==``-контракт сохранён).
    """
    if not deep:
        result = defaults.copy()
        result.update(data)
        return result

    return deep_merge(defaults, data)


def extract_fields(
    data: Dict[str, Any],
    fields: Set[str],
    nested: bool = False,
) -> Dict[str, Any]:
    """
    Извлечь указанные поля из данных.

    Args:
        fields: Множество имен полей для извлечения
        nested: Поддерживать точечную нотацию для вложенных полей
    """
    if not nested:
        return {k: v for k, v in data.items() if k in fields}

    result = {}

    for field_path in fields:
        if "." in field_path:
            value = get_nested_value(data, field_path)
            if value is not None:
                set_nested_value(result, field_path, value)
        else:
            if field_path in data:
                result[field_path] = data[field_path]

    return result


def get_model_fields(model_class: type[BaseModel]) -> List[str]:
    """Получить список полей Pydantic модели."""
    return list(model_class.model_fields.keys())


def get_model_defaults(model_class: type[BaseModel]) -> Dict[str, Any]:
    """Получить дефолтные значения полей Pydantic модели."""
    instance = model_class()
    return instance.model_dump(exclude_unset=True)


def get_model_schema(model_class: type[BaseModel]) -> Dict[str, Any]:
    """
    Построить словарь-схему по Pydantic модели.

    Возвращает структуру:
        {field_name: {"type": str, "default": value, "description": str, ...}}
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
    separator: str = ".",
    prefix: str = "",
) -> Dict[str, Any]:
    """
    Преобразовать вложенный словарь в плоский с точечной нотацией.

    Example:
        data = {"database": {"host": "localhost", "port": 5432}}
        result = flatten_dict(data)
        # {"database.host": "localhost", "database.port": 5432}
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
    separator: str = ".",
) -> Dict[str, Any]:
    """
    Преобразовать плоский словарь с точечной нотацией во вложенный.

    Example:
        data = {"database.host": "localhost", "database.port": 5432}
        result = unflatten_dict(data)
        # {"database": {"host": "localhost", "port": 5432}}
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
    current_depth: int = 0,
) -> Any:
    """Рекурсивно конвертировать все ссылки в структуре данных."""
    return _convert_all_references(data, resolver, max_depth, current_depth)
