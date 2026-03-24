# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

DataConverter и FormatType перемещены в serialization/converter.py.

Используйте новый путь:
    from data_schema_module.serialization import DataConverter, FormatType
    from data_schema_module import DataConverter, FormatType
"""
from ..serialization.converter import DataConverter, FormatType

__all__ = ["DataConverter", "FormatType"]
