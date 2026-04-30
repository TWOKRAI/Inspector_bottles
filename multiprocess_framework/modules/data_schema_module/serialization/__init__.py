# -*- coding: utf-8 -*-
"""
Сериализация данных.

Содержит:
    DataConverter  — конвертация между dict/JSON/YAML/Model
    FormatType     — enum форматов
    RegistersIO    — IO для объектов с model_dump_all/model_validate_all
    FileStorage    — хранилище в JSON-файлах (реализует ISchemaStorage)
"""
from .converter import DataConverter, FormatType
from .io import (
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_yaml,
    registers_from_yaml,
    registers_to_flat_dict,
    registers_from_flat_dict,
)
from .file_storage import FileStorage

__all__ = [
    "DataConverter",
    "FormatType",
    "registers_to_dict",
    "registers_from_dict",
    "registers_to_json",
    "registers_from_json",
    "registers_to_yaml",
    "registers_from_yaml",
    "registers_to_flat_dict",
    "registers_from_flat_dict",
    "FileStorage",
]
