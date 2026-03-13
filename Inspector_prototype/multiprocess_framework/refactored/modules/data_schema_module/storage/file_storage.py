# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

FileStorage перемещён в serialization/file_storage.py.

Используйте новый путь:
    from data_schema_module.serialization import FileStorage
    from data_schema_module import FileStorage
"""
from ..serialization.file_storage import FileStorage

__all__ = ["FileStorage"]
