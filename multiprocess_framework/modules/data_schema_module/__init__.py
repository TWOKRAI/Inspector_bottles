# -*- coding: utf-8 -*-
"""
data_schema_module — ядро описания структур данных для многопроцессного фреймворка.

Single source of truth для регистров и схем: на одном `SchemaBase`-наследнике с
`FieldMeta` + `FieldRouting` собирается тип, валидация, UI-метаданные, дефолт и
маршрут между процессами. Реестр (`SchemaRegistry`) связывает имя ↔ класс схемы;
сериализация (`DataConverter`) переводит модели в dict/JSON/YAML на границе
процессов (Dict at Boundary, ADR-008).

## Архитектура слоёв

| Слой | Поддиректория | Зависимости | Назначение |
|------|---------------|-------------|------------|
| Domain (zero deps) | `core/` | только Pydantic v2 / typing | SchemaBase, FieldMeta, FieldRouting, validators, exceptions, helpers |
| Application | `registry/`, `container/`, `serialization/` | `core/` | SchemaRegistry, RegistersContainer, DataConverter |
| Application | `factory/`, `models/`, `versioning/`, `api/`, `tools/` | `core/` (+ optional) | ModelFactory, ComponentDNA, VersionManager, simple_api, SchemaVisualizer |
| Infrastructure | `storage/` | `core/` + `process_module` | StorageManager, ProcessDataContainer |
| Изолятор | `extensions/` | re-export из `factory/`, `tools/`, `versioning/`, `api/` | Контролирует side-effects (ADR-DS-004) |
| Контракты | `interfaces.py` | typing.Protocol | 30+ Protocol/ABC для адаптеров и type checking |

## Публичный фасад

Импортируйте всё через корень модуля:

```python
from multiprocess_framework.modules.data_schema_module import (
    SchemaBase, FieldMeta, FieldRouting,   # 95% случаев
    register_schema, SchemaRegistry,       # реестр
    DataConverter, FormatType,             # сериализация
    process, RegistersContainer,           # конфиги
)
```

Прямые импорты в обход фасада (`from data_schema_module.core.field_meta import …`)
**не рекомендуются** — нарушают R-1 «единый канал импортов» и засоряют DSM
file-to-file edges. Исключение — `extensions/*` и `storage/*` для опциональных
компонентов (ADR-DS-004).

См. также: [README.md](README.md), [STATUS.md](STATUS.md), [DECISIONS.md](DECISIONS.md),
[interfaces.py](interfaces.py) (публичный контракт).
"""
from __future__ import annotations

__version__ = "2.0.0"

# =============================================================================
# LAYER 0: ПУБЛИЧНЫЕ КОНТРАКТЫ (Protocol / ABC)
# =============================================================================
from .interfaces import (
    HasBuild,
    IAsyncRegisterStorage,
    IAsyncSchemaStorage,
    IDataConverter,
    IDataValidator,
    IDocumentationFormatter,
    IRegisterStorage,
    ISchema,
    ISchemaAdapter,
    ISchemaDocumentationGenerator,
    ISchemaManager,
    ISchemaRegistry,
    ISchemaStorage,
    ISchemaVisualizer,
    IStorageManager,
    IVersionManager,
    IVisualizationFormatter,
)

# =============================================================================
# LAYER 1: DOMAIN — Schema, поля, исключения (core/, zero dependencies)
# =============================================================================
from .core.exceptions import (
    DataManagerError,
    DataSchemaError,
    InvalidParameterError,
    SchemaNotFoundError,
    SchemaRegistrationError,
    SchemaValidationError,
    VersionManagerError,
)
from .core.field_meta import FieldMeta
from .core.field_routing import FieldRouting
from .core.field_types import (
    FpsLimit,
    HsvChannel,
    HsvHue,
    ImageScale,
    Milliseconds,
    NetworkPort,
    NormalizedFloat,
    Percent,
    Pixels,
    Scale,
    Seconds,
    get_field_type,
    register_field_type,
)
from .core.helpers import (
    extract_fields,
    get_model_schema,
    get_nested_value,
    merge_with_defaults,
    set_nested_value,
)
from .core.reference import (
    DataReference,
    convert_all_references,
    convert_reference_to_data,
    is_reference,
)
from .core.register_dispatch import RegisterDispatchMeta
from .core.schema_base import RegisterBase, SchemaBase
from .core.schema_mixin import RegisterMixin, SchemaMixin
from .core.validators import DataValidator

# =============================================================================
# LAYER 2: APPLICATION — Registry, Discovery (registry/)
# =============================================================================
from .registry.discovery import (
    RegistersScanner,
    discover_registers_from_package,
    register_package_registers,
    register_package_schemas,
)
from .registry.schema_registry import (
    SchemaManager,
    SchemaRegistry,
    get_default_registry,
    register_schema,
)

# =============================================================================
# LAYER 3: APPLICATION — Сериализация (serialization/)
# =============================================================================
from .serialization.converter import DataConverter, FormatType
from .serialization.file_storage import FileStorage
from .serialization.io import (
    registers_from_dict,
    registers_from_flat_dict,
    registers_from_json,
    registers_from_yaml,
    registers_to_dict,
    registers_to_flat_dict,
    registers_to_json,
    registers_to_yaml,
)

# =============================================================================
# LAYER 4: APPLICATION — Container, config converters (container/)
# =============================================================================
from .container.config_converters import (
    build_process_with_workers,
    config_to_dict,
    configs_to_dicts,
    process,
)
from .container.registers_container import RegistersContainer

# =============================================================================
# Публичный API
# =============================================================================
# Структура списка повторяет порядок слоёв выше для удобства навигации.
__all__ = [
    # --- Layer 0: Контракты (Protocol/ABC) ---
    "HasBuild",
    "IAsyncRegisterStorage",
    "IAsyncSchemaStorage",
    "IDataConverter",
    "IDataValidator",
    "IDocumentationFormatter",
    "IRegisterStorage",
    "ISchema",
    "ISchemaAdapter",
    "ISchemaDocumentationGenerator",
    "ISchemaManager",
    "ISchemaRegistry",
    "ISchemaStorage",
    "ISchemaVisualizer",
    "IStorageManager",
    "IVersionManager",
    "IVisualizationFormatter",
    # --- Layer 1: Domain ---
    "SchemaBase",
    "RegisterBase",
    "SchemaMixin",
    "RegisterMixin",
    "FieldMeta",
    "FieldRouting",
    "RegisterDispatchMeta",
    "DataValidator",
    # Field types
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
    # Exceptions
    "DataSchemaError",
    "SchemaNotFoundError",
    "SchemaValidationError",
    "SchemaRegistrationError",
    "InvalidParameterError",
    "DataManagerError",
    "VersionManagerError",
    # Helpers / references
    "get_nested_value",
    "set_nested_value",
    "merge_with_defaults",
    "extract_fields",
    "get_model_schema",
    "DataReference",
    "is_reference",
    "convert_reference_to_data",
    "convert_all_references",
    # --- Layer 2: Registry ---
    "SchemaRegistry",
    "SchemaManager",
    "register_schema",
    "get_default_registry",
    "RegistersScanner",
    "discover_registers_from_package",
    "register_package_schemas",
    "register_package_registers",
    # --- Layer 3: Serialization ---
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
    # --- Layer 4: Container ---
    "RegistersContainer",
    "config_to_dict",
    "configs_to_dicts",
    "build_process_with_workers",
    "process",
    # --- Module metadata ---
    "__version__",
]
