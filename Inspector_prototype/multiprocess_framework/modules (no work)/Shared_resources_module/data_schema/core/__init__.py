"""
Базовые компоненты модуля data_schema.

Содержит интерфейсы, исключения и метрики.
"""

from .interfaces import (
    ISchemaRegistry,
    IStorageManager,
    IVersionManager,
    IDataConverter,
    IDataValidator,
)
from .exceptions import (
    DataSchemaError,
    SchemaNotFoundError,
    SchemaValidationError,
    SchemaRegistrationError,
    InvalidParameterError,
    DataManagerError,
    VersionManagerError,
)
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
    'ISchemaRegistry',
    'IStorageManager',
    'IVersionManager',
    'IDataConverter',
    'IDataValidator',
    
    # Исключения
    'DataSchemaError',
    'SchemaNotFoundError',
    'SchemaValidationError',
    'SchemaRegistrationError',
    'InvalidParameterError',
    'DataManagerError',
    'VersionManagerError',
    
    # Метрики
    'MetricsCollector',
    'get_metrics_collector',
    'record_metric',
    'increment_metric',
    'record_timing',
    'timed',
]


