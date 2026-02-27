"""
Data Schema Module - Универсальная система работы с данными на основе Pydantic v2.

Этот модуль инкапсулирует всю логику для работы с дата-классами и схемами данных.
Использует гибридный подход: dict в ProcessData, Pydantic модели в коде.

Основные возможности:
- Создание схем из Pydantic моделей
- Валидация данных через Pydantic v2
- Конвертация между форматами (JSON, YAML, dict, Pydantic model)
- Работа с дефолтными значениями
- Автоматическая синхронизация с ProcessData
"""

# Основные компоненты
from .registry.schema_registry import SchemaRegistry, register_schema
from .storage.storage_manager import StorageManager
from .api.manager_adapter import ManagerDataAdapter
from .factory.model_factory import ModelFactory

# Интерфейсы
from .core.interfaces import (
    ISchemaRegistry,
    IStorageManager,
    IVersionManager,
    IDataConverter,
    IDataValidator,
)

# Модели
from .models import BaseComponentModel, BaseManagerModel, ComponentType

# Конвертеры и валидаторы
from .utils.converters import DataConverter, FormatType
from .utils.validators import DataValidator

# Утилиты
from .utils.helpers import (
    get_nested_value,
    set_nested_value,
    merge_with_defaults,
    extract_fields,
)

# Версионирование
from .versioning.version_manager import VersionManager, VersionInfo

# Исключения
from .core.exceptions import (
    DataSchemaError,
    SchemaNotFoundError,
    SchemaValidationError,
    SchemaRegistrationError,
    InvalidParameterError,
    DataManagerError,
    VersionManagerError,
)

# Метрики
from .core.metrics import (
    MetricsCollector,
    get_metrics_collector,
    record_metric,
    increment_metric,
    record_timing,
    timed,
)

# Упрощенный API для простых случаев
from .api.simple_api import (
    create_config,
    create_manager_config,
    get_config,
    config_from_dict,
    auto_config,
)

# ДНК компонентов
try:
    from .factory.dna_factory import DNAFactory
    from .storage.process_data_container import ProcessDataContainer
    from .models.dna import (
        ComponentDNA,
        ComponentLocation,
        ResourceReference,
        ResourceType,
        ComponentHierarchy
    )
    _has_dna = True
except ImportError:
    _has_dna = False

# Ссылки и миграции
from .utils.reference import DataReference, is_reference, convert_reference_to_data, convert_all_references
from .utils.migration import from_dataclass, from_dict, from_json, from_yaml

# Инструменты для работы со схемами
from .tools.schema_visualizer import SchemaVisualizer
from .tools.schema_documentation_generator import SchemaDocumentationGenerator

# Алиасы для обратной совместимости
SchemaManager = SchemaRegistry  # Обратная совместимость

__all__ = [
    # Основные компоненты
    'SchemaRegistry',
    'SchemaManager',  # Алиас для обратной совместимости
    'StorageManager',
    'ManagerDataAdapter',
    'ModelFactory',
    'register_schema',  # Декоратор для автоматической регистрации
    
    # Интерфейсы
    'ISchemaRegistry',
    'IStorageManager',
    'IVersionManager',
    'IDataConverter',
    'IDataValidator',
    
    # Модели
    'BaseComponentModel',
    'BaseManagerModel',
    'ComponentType',
    
    # Конвертеры и валидаторы
    'DataConverter',
    'DataValidator',
    'FormatType',
    
    # Утилиты
    'get_nested_value',
    'set_nested_value',
    'merge_with_defaults',
    'extract_fields',
    
    # Версионирование
    'VersionManager',
    'VersionInfo',

    # Ссылки
    'DataReference',
    'is_reference',
    'convert_reference_to_data',
    'convert_all_references',

    # Миграция
    'from_dataclass',
    'from_dict',
    'from_json',
    'from_yaml',
    
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
    
    # Упрощенный API
    'create_config',
    'create_manager_config',
    'get_config',
    'config_from_dict',
    'auto_config',
    
    # Инструменты
    'SchemaVisualizer',
    'SchemaDocumentationGenerator',
]

# Добавляем ДНК компонентов если доступны
if _has_dna:
    __all__.extend([
        'DNAFactory',
        'ProcessDataContainer',
        'ComponentDNA',
        'ComponentLocation',
        'ResourceReference',
        'ResourceType',
        'ComponentHierarchy',
    ])

