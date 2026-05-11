# -*- coding: utf-8 -*-
"""
Ядро data_schema_module.

Содержит все компоненты без зависимостей от других модулей фреймворка:
    - SchemaBase / RegisterBase (backward compat alias)
    - SchemaMixin / RegisterMixin (backward compat alias)
    - FieldMeta, FieldRouting, field_types
    - Exceptions, Validators
    - Interfaces ядра (ISchema, ISchemaAdapter, HasBuild, IDataValidator);
      контракты других слоёв — в `<sub_package>/interfaces.py` (ADR-DS-005).
    - Metrics
"""
# Интерфейсы ядра (другие — в registry/, serialization/, storage/, versioning/, tools/)
from .interfaces import (
    HasBuild,
    IDataValidator,
    ISchema,
    ISchemaAdapter,
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
from .register_dispatch import RegisterDispatchMeta
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
    # Интерфейсы ядра (другие слои — в <sub_package>/interfaces.py)
    "ISchema",
    "ISchemaAdapter",
    "HasBuild",
    "IDataValidator",
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
    "RegisterDispatchMeta",
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
