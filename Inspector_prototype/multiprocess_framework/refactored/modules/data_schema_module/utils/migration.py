"""
Хелперы для миграции из старых форматов (dataclass/JSON/YAML) в Pydantic модели.
"""

from typing import Any, Dict, Optional, Type
from pathlib import Path
from dataclasses import asdict, is_dataclass

from pydantic import BaseModel

from ..registry.schema_registry import SchemaManager
from .converters import DataConverter, FormatType


def from_dataclass(obj: Any, schema_name: Optional[str] = None) -> BaseModel:
    """Конвертировать dataclass в Pydantic модель."""
    if not is_dataclass(obj):
        raise TypeError("obj должен быть dataclass")
    data = asdict(obj)
    registry = SchemaManager.get_instance()
    name = schema_name or data.get("component_class") or type(obj).__name__
    return registry.create_instance(name, data)


def from_dict(data: Dict[str, Any], schema_name: Optional[str] = None) -> BaseModel:
    """Конвертировать словарь в Pydantic модель."""
    registry = SchemaManager.get_instance()
    name = schema_name or data.get("component_class") or "BaseManagerModel"
    return registry.create_instance(name, data)


def from_json(src: Any, schema_name: Optional[str] = None) -> BaseModel:
    """Конвертировать JSON (строка или путь) в Pydantic модель."""
    data = DataConverter.convert(src, FormatType.JSON, FormatType.DICT)
    return from_dict(data, schema_name)


def from_yaml(src: Any, schema_name: Optional[str] = None) -> BaseModel:
    """Конвертировать YAML (строка или путь) в Pydantic модель."""
    data = DataConverter.convert(src, FormatType.YAML, FormatType.DICT)
    return from_dict(data, schema_name)

