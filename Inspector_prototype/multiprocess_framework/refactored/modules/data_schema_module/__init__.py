# -*- coding: utf-8 -*-
"""
data_schema_module — Универсальная система работы с данными на основе Pydantic v2.

Архитектура:
    ┌─────────────────────────────────────────────────────┐
    │  Поля (fields/)                                      │
    │  FieldMeta — метаданные поля (Annotated-дескриптор) │
    │  RegisterMixin — 5 секций методов                    │
    │  RegisterBase  — RegisterMixin + BaseModel           │
    ├─────────────────────────────────────────────────────┤
    │  Контейнер (utils/registers_container.py)            │
    │  RegistersContainer — набор регистров + IO           │
    ├─────────────────────────────────────────────────────┤
    │  Реестр (registry/)                                  │
    │  SchemaManager, discover_registers_from_package      │
    ├─────────────────────────────────────────────────────┤
    │  Хранение (storage/)                                 │
    │  StorageManager (ProcessData) + FileStorage (JSON)   │
    ├─────────────────────────────────────────────────────┤
    │  Версионирование (versioning/)                       │
    │  VersionManager — история + откат конфигов           │
    ├─────────────────────────────────────────────────────┤
    │  Компоненты и ДНК (models/)                         │
    │  BaseComponentModel, BaseManagerModel, ComponentDNA  │
    └─────────────────────────────────────────────────────┘

Быстрый старт (регистры и конфиги):

    from typing import Annotated
    from multiprocess_framework.refactored.modules.data_schema_module import (
        FieldMeta, RegisterBase, RegistersContainer,
        discover_registers_from_package,
    )

    class DrawRegisters(RegisterBase):
        dp: Annotated[float, FieldMeta("Разрешение", min=0.1, max=20.0)] = 1.4

    r = DrawRegisters()
    r.dp                             # → 1.4
    r.get_field_meta("dp").max       # → 20.0
    r.update_field("dp", 2.0)        # → (True, None)

Быстрый старт (компоненты и хранение в ProcessData):

    from multiprocess_framework.refactored.modules.data_schema_module import (
        SchemaManager, ModelFactory, StorageManager, register_schema,
    )

    @register_schema("MyConfig")
    class MyConfig(BaseModel):
        host: str = "localhost"
        port: int = 8080

    obj = ModelFactory.create("MyConfig", {"host": "0.0.0.0"})

Персистентность через FileStorage:

    from multiprocess_framework.refactored.modules.data_schema_module import FileStorage
    s = FileStorage("data/registers")
    container.save(s, "main_process")
    container.load(s, "main_process")
"""

# --- Поля: ядро архитектуры ---
from .fields import (
    FieldMeta,
    FieldRouting,
    RegisterMixin,
    RegisterBase,
    # Переиспользуемые type aliases
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

# --- Реестр схем, авто-дискавери, сканер, межпроцессный реестр ---
from .registry.schema_registry import SchemaManager, register_schema
from .registry.register_discovery import (
    discover_registers_from_package,
    register_package_registers,
    register_package_schemas,
)
from .registry.registers_scanner import RegistersScanner
from .registry.process_registry import ProcessRegistersRegistry, RegistersMeta

# --- Контейнер регистров ---
from .utils.registers_container import RegistersContainer

# --- Хранилище ---
from .storage.storage_manager import StorageManager
from .storage.file_storage import FileStorage

# --- Адаптеры и фабрика ---
from .api.manager_adapter import ManagerDataAdapter
from .factory.model_factory import ModelFactory

# --- Интерфейсы ---
from .core.interfaces import (
    ISchemaManager,
    IStorageManager,
    IVersionManager,
    IDataConverter,
    IDataValidator,
    IRegisterStorage,
    IAsyncRegisterStorage,
    HasBuild,
)

# --- Модели компонентов ---
from .models import BaseComponentModel, BaseManagerModel, ComponentType

# --- Конвертеры и валидаторы ---
from .utils.converters import DataConverter, FormatType
from .utils.validators import DataValidator

# --- Вспомогательные утилиты ---
from .utils.helpers import (
    get_nested_value,
    set_nested_value,
    merge_with_defaults,
    extract_fields,
    get_model_schema,
)
from .utils.config_converters import (
    config_to_dict,
    configs_to_dicts,
    build_process_with_workers,
    process,
)
from .utils.registers_io import (
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_yaml,
    registers_from_yaml,
    registers_to_flat_dict,
    registers_from_flat_dict,
)

# --- Версионирование ---
from .versioning.version_manager import VersionManager, VersionInfo

# --- Исключения ---
from .core.exceptions import (
    DataSchemaError,
    SchemaNotFoundError,
    SchemaValidationError,
    SchemaRegistrationError,
    InvalidParameterError,
    DataManagerError,
    VersionManagerError,
)

# --- Метрики ---
from .core.metrics import (
    MetricsCollector,
    get_metrics_collector,
    record_metric,
    increment_metric,
    record_timing,
    timed,
)

# --- Упрощённый API ---
from .api.simple_api import (
    create_config,
    create_manager_config,
    get_config,
    config_from_dict,
    auto_config,
)

# --- Ссылки ---
from .utils.reference import (
    DataReference,
    is_reference,
    convert_reference_to_data,
    convert_all_references,
)

# --- Инструменты ---
from .tools.schema_visualizer import SchemaVisualizer
from .tools.schema_documentation_generator import SchemaDocumentationGenerator

# --- ДНК компонентов (опционально) ---
try:
    from .factory.dna_factory import DNAFactory
    from .storage.process_data_container import ProcessDataContainer
    from .models.dna import (
        ComponentDNA,
        ComponentLocation,
        ResourceReference,
        ResourceType,
        ComponentHierarchy,
    )
    _has_dna = True
except ImportError:
    _has_dna = False

__all__ = [
    # Поля — основа архитектуры
    "FieldMeta",
    "FieldRouting",
    "RegisterMixin",
    "RegisterBase",
    # Переиспользуемые type aliases
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
    # Реестр
    "SchemaManager",
    "register_schema",
    "discover_registers_from_package",
    "register_package_registers",
    "register_package_schemas",
    "RegistersScanner",
    "ProcessRegistersRegistry",
    "RegistersMeta",
    # Контейнер
    "RegistersContainer",
    # Хранилище
    "StorageManager",
    "FileStorage",
    # Адаптеры и фабрика
    "ManagerDataAdapter",
    "ModelFactory",
    # Интерфейсы
    "ISchemaManager",
    "IStorageManager",
    "IVersionManager",
    "IDataConverter",
    "IDataValidator",
    "IRegisterStorage",
    "IAsyncRegisterStorage",
    "HasBuild",
    # Модели компонентов
    "BaseComponentModel",
    "BaseManagerModel",
    "ComponentType",
    # Конвертеры и валидаторы
    "DataConverter",
    "DataValidator",
    "FormatType",
    # Утилиты
    "get_nested_value",
    "set_nested_value",
    "merge_with_defaults",
    "extract_fields",
    "get_model_schema",
    "registers_to_dict",
    "registers_from_dict",
    "registers_to_json",
    "registers_from_json",
    "registers_to_yaml",
    "registers_from_yaml",
    "registers_to_flat_dict",
    "registers_from_flat_dict",
    # Dict at Boundary
    "config_to_dict",
    "configs_to_dicts",
    "build_process_with_workers",
    "process",
    # Версионирование
    "VersionManager",
    "VersionInfo",
    # Ссылки
    "DataReference",
    "is_reference",
    "convert_reference_to_data",
    "convert_all_references",
    # Исключения
    "DataSchemaError",
    "SchemaNotFoundError",
    "SchemaValidationError",
    "SchemaRegistrationError",
    "InvalidParameterError",
    "DataManagerError",
    "VersionManagerError",
    # Метрики
    "MetricsCollector",
    "get_metrics_collector",
    "record_metric",
    "increment_metric",
    "record_timing",
    "timed",
    # Упрощённый API
    "create_config",
    "create_manager_config",
    "get_config",
    "config_from_dict",
    "auto_config",
    # Инструменты
    "SchemaVisualizer",
    "SchemaDocumentationGenerator",
]

if _has_dna:
    __all__ += [
        "DNAFactory",
        "ProcessDataContainer",
        "ComponentDNA",
        "ComponentLocation",
        "ResourceReference",
        "ResourceType",
        "ComponentHierarchy",
    ]
