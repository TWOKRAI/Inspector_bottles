# -*- coding: utf-8 -*-
"""
Backward compatibility re-exports.

Этот файл содержит все символы, которые были в старом __init__.py,
но не входят в новый минимальный публичный API.

Импортируется автоматически из __init__.py для обратной совместимости.
При миграции на новый API используйте явные пути:

    # Старый импорт (работает через _compat):
    from data_schema_module import SchemaManager, StorageManager

    # Новый рекомендуемый импорт:
    from data_schema_module.registry import SchemaRegistry, get_default_registry
    from data_schema_module.extensions.storage_manager import StorageManager
"""

# Backward compat: старые имена классов
from .core.schema_base import RegisterBase  # SchemaBase alias
from .core.schema_mixin import RegisterMixin  # SchemaMixin alias
from .registry.schema_registry import SchemaManager  # SchemaRegistry alias
from .interfaces import IRegisterStorage, IAsyncRegisterStorage  # ISchemaStorage aliases
from .interfaces import ISchemaManager  # backward compat ABC

# Расширенные компоненты (зависят от внешних модулей)
from .extensions.storage_manager import StorageManager
from .extensions.manager_adapter import ManagerDataAdapter
from .extensions.factory import ModelFactory
from .extensions.versioning import VersionManager, VersionInfo
from .extensions.models import BaseComponentModel, BaseManagerModel, ComponentType

# Инструменты (опциональные)
from .extensions.tools import SchemaVisualizer, SchemaDocumentationGenerator

# Упрощённый API
from .extensions.simple_api import (
    create_config,
    create_manager_config,
    get_config,
    config_from_dict,
    auto_config,
)

# Метрики
from .extensions.metrics import (
    MetricsCollector,
    get_metrics_collector,
    record_metric,
    increment_metric,
    record_timing,
    timed,
)

# Межпроцессный реестр
from .registry.process_registry import ProcessRegistersRegistry, RegistersMeta

# ДНК компонентов (опционально)
_has_dna = False
try:
    from .extensions.factory import DNAFactory
    from .extensions.process_data_container import ProcessDataContainer
    from .extensions.models import (
        ComponentDNA,
        ComponentLocation,
        ResourceReference,
        ResourceType,
        ComponentHierarchy,
    )
    _has_dna = True
except ImportError:
    pass
