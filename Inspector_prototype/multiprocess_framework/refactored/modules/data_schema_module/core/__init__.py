# -*- coding: utf-8 -*-
"""
Ядро data_schema_module.

Содержит все компоненты без зависимостей от других модулей фреймворка:
    - SchemaBase / RegisterBase (backward compat alias)
    - SchemaMixin / RegisterMixin (backward compat alias)
    - FieldMeta, FieldRouting, field_types
    - Exceptions, Validators
    - Interfaces (re-export из корневого interfaces.py)
    - Metrics
"""
# Интерфейсы (re-export из корня)
from .interfaces import (
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
    # Backward compat
    IRegisterStorage,
    IAsyncRegisterStorage,
    ISchemaManager,
)

# Исключения
from .exceptions import (
    DataSchemaError,
    SchemaNotFoundError,
    SchemaValidationError,
    SchemaRegistrationError,
    InvalidParameterError,
    DataManagerError,
    VersionManagerError,
)

# Ядро схем
from .field_meta import FieldMeta
from .field_routing import FieldRouting
from .field_types import (
    Percent,
    NormalizedFloat,
    Scale,
    Milliseconds,
    Seconds,
    Pixels,
    ImageScale,
    HsvHue,
    HsvChannel,
    NetworkPort,
    FpsLimit,
)
from .schema_mixin import SchemaMixin, RegisterMixin
from .schema_base import SchemaBase, RegisterBase

# Валидаторы
from .validators import DataValidator

# Метрики
from .metrics import (
    MetricsCollector,
    get_metrics_collector,
    record_metric,
    increment_metric,
    record_timing,
    timed,
)

__all__ = [
    # Интерфейсы
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
    "IRegisterStorage",
    "IAsyncRegisterStorage",
    "ISchemaManager",
    # Исключения
    "DataSchemaError",
    "SchemaNotFoundError",
    "SchemaValidationError",
    "SchemaRegistrationError",
    "InvalidParameterError",
    "DataManagerError",
    "VersionManagerError",
    # Ядро схем
    "FieldMeta",
    "FieldRouting",
    "Percent",
    "NormalizedFloat",
    "Scale",
    "Milliseconds",
    "Seconds",
    "Pixels",
    "ImageScale",
    "HsvHue",
    "HsvChannel",
    "NetworkPort",
    "FpsLimit",
    "SchemaMixin",
    "RegisterMixin",
    "SchemaBase",
    "RegisterBase",
    # Валидаторы
    "DataValidator",
    # Метрики
    "MetricsCollector",
    "get_metrics_collector",
    "record_metric",
    "increment_metric",
    "record_timing",
    "timed",
]
