# -*- coding: utf-8 -*-
"""
data_schema_module — Независимое ядро для описания структур данных.

Архитектура:
    core/          Ядро: SchemaBase, FieldMeta, validators
    registry/      Реестр схем (без Singleton)
    serialization/ Сериализация: dict/JSON/YAML, FileStorage
    container/     RegistersContainer, config_converters
    interfaces.py  Публичный контракт (протоколы и ABC)

Расширения (явный импорт):
    from data_schema_module.storage.storage_manager import StorageManager
    from data_schema_module.extensions.versioning import VersionManager
"""
# =============================================================================
# Публичный контракт (интерфейсы)
# =============================================================================
from .interfaces import (
    ISchema,
    ISchemaRegistry,
    ISchemaAdapter,
    ISchemaStorage,
    IAsyncSchemaStorage,
    HasBuild,
    IDataConverter,
    IDataValidator,
    IRegisterStorage,
    IAsyncRegisterStorage,
    ISchemaManager,
    IVisualizationFormatter,
    IDocumentationFormatter,
    ISchemaVisualizer,
    ISchemaDocumentationGenerator,
    IStorageManager,
    IVersionManager,
)

# =============================================================================
# Ядро: схемы и поля
# =============================================================================
from .core.schema_base import SchemaBase, RegisterBase
from .core.schema_mixin import SchemaMixin, RegisterMixin
from .core.field_meta import FieldMeta
from .core.field_routing import FieldRouting
from .core.register_dispatch import RegisterDispatchMeta
from .core.field_types import (
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
    register_field_type,
    get_field_type,
)
from .core.exceptions import (
    DataSchemaError,
    SchemaNotFoundError,
    SchemaValidationError,
    SchemaRegistrationError,
    InvalidParameterError,
    DataManagerError,
    VersionManagerError,
)
from .core.validators import DataValidator
from .core.helpers import (
    get_nested_value,
    set_nested_value,
    merge_with_defaults,
    extract_fields,
    get_model_schema,
)
from .core.reference import (
    DataReference,
    is_reference,
    convert_reference_to_data,
    convert_all_references,
)

# =============================================================================
# Реестр схем
# =============================================================================
from .registry.schema_registry import (
    SchemaRegistry,
    SchemaManager,
    register_schema,
    get_default_registry,
)
from .registry.discovery import (
    RegistersScanner,
    discover_registers_from_package,
    register_package_schemas,
    register_package_registers,
)

# =============================================================================
# Сериализация
# =============================================================================
from .serialization.converter import DataConverter, FormatType
from .serialization.io import (
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_yaml,
    registers_from_yaml,
    registers_to_flat_dict,
    registers_from_flat_dict,
)
from .serialization.file_storage import FileStorage

# =============================================================================
# Контейнеры
# =============================================================================
from .container.registers_container import RegistersContainer
from .container.config_converters import (
    config_to_dict,
    configs_to_dicts,
    build_process_with_workers,
    process,
)

# =============================================================================
# Публичный API (ядро)
# =============================================================================
__all__ = [
    "ISchema",
    "ISchemaRegistry",
    "ISchemaAdapter",
    "ISchemaStorage",
    "IAsyncSchemaStorage",
    "HasBuild",
    "IDataConverter",
    "IDataValidator",
    "IRegisterStorage",
    "IAsyncRegisterStorage",
    "ISchemaManager",
    "IVisualizationFormatter",
    "IDocumentationFormatter",
    "ISchemaVisualizer",
    "ISchemaDocumentationGenerator",
    "IStorageManager",
    "IVersionManager",
    "SchemaBase",
    "RegisterBase",
    "SchemaMixin",
    "RegisterMixin",
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
    "register_field_type",
    "get_field_type",
    "DataSchemaError",
    "SchemaNotFoundError",
    "SchemaValidationError",
    "SchemaRegistrationError",
    "InvalidParameterError",
    "DataManagerError",
    "VersionManagerError",
    "DataValidator",
    "get_nested_value",
    "set_nested_value",
    "merge_with_defaults",
    "extract_fields",
    "get_model_schema",
    "DataReference",
    "is_reference",
    "convert_reference_to_data",
    "convert_all_references",
    "SchemaRegistry",
    "SchemaManager",
    "register_schema",
    "get_default_registry",
    "RegistersScanner",
    "discover_registers_from_package",
    "register_package_schemas",
    "register_package_registers",
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
    "RegistersContainer",
    "config_to_dict",
    "configs_to_dicts",
    "build_process_with_workers",
    "process",
]
