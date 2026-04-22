# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

Интерфейсы перемещены в корень модуля: data_schema_module/interfaces.py
Этот файл сохранён для обратной совместимости — все старые импорты работают.

Используйте новый путь:
    from data_schema_module.interfaces import ISchemaRegistry, ISchemaStorage, ...
"""
from ..interfaces import (
    ISchema,
    ISchemaRegistry,
    ISchemaAdapter,
    ISchemaStorage,
    IAsyncSchemaStorage,
    HasBuild,
    IDataConverter,
    IDataValidator,
    IVisualizationFormatter,
    IDocumentationFormatter,
    ISchemaVisualizer,
    ISchemaDocumentationGenerator,
    IStorageManager,
    IVersionManager,
    # Backward compat aliases
    IRegisterStorage,
    IAsyncRegisterStorage,
    ISchemaManager,
)

__all__ = [
    "ISchema",
    "ISchemaRegistry",
    "ISchemaAdapter",
    "ISchemaStorage",
    "IAsyncSchemaStorage",
    "HasBuild",
    "IDataConverter",
    "IDataValidator",
    "IVisualizationFormatter",
    "IDocumentationFormatter",
    "ISchemaVisualizer",
    "ISchemaDocumentationGenerator",
    "IStorageManager",
    "IVersionManager",
    # Backward compat
    "IRegisterStorage",
    "IAsyncRegisterStorage",
    "ISchemaManager",
]
